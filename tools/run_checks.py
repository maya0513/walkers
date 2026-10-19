#!/usr/bin/env python3
"""Offline validation. Leaves concise reports plus full diagnostic logs."""
import concurrent.futures
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from godot_validation_support import classify_errors

ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/"reports"

def posture_report(summary):
    rows=[]
    for rate in [30,60,120]:
        for case in summary["runtime"][str(rate)]["cases"]:
            if case["name"] in ["walk","jog"]:
                knees=case["midstance_knees"]
                knee=f"{max(value['max_flex_degrees'] for value in knees.values()):.2f}" if case["name"]=="walk" else "対象外"
                rows.append(f"| {rate} | {case['name']} | {case['head_height']['peak_to_peak_m']*100:.2f} | {knee} | {case['body_height_after_settle']['range_m']*1000:.3f} | {case['grounded_ratio']*100:.1f} |")
    return """## 頭の上下動と支持姿勢

| 描画fps | モーション | 頭部基準点の上下幅 cm | 歩行中間支持期の膝屈曲 最大° | 衝突主体の上下幅 mm | 接地率 % |
|---|---|---|---|---|---|
"""+"\n".join(rows)+"""

平地の定速区間を同時刻の最終骨姿勢で計測しています。頭部の値は頭骨の基準点であり、頭頂や全身重心の変位とは異なります。頭を空間へ固定せず、脚・骨盤の連続した動きで揺れを抑えました。Blender単体の姿勢と、Godotの接地補正後の最終姿勢を別に測っています。

歩行の中間支持期は左右それぞれのサンプルを確認し、膝屈曲20度以内という今回の演出上の基準を満たしました。支持点ずれの計測にも左右それぞれ8点以上の対象サンプルがあることを検査し、対象区間が空のために合格することを防いでいます。詳細な点数はJSONに記録しています。衝突主体の上下幅と接地率は、平地で偽の段差処理や沈み込みが発生していないことの確認です。

頭・体幹・重心の違いと参考文献は[人間向けの解説](../docs/gait_reference.ja.md)を参照してください。これらの角度・上下幅の上限は作品の表現設定であり、万人の歩き方の医学的な推奨値ではありません。

"""

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--allow-editor-socket-errors",action="store_true",help="Record a sandbox's blocked optional editor TCP services separately; project errors still fail")
    options=parser.parse_args()
    limitations={}
    REPORTS.mkdir(exist_ok=True)
    godot=shutil.which("godot") or shutil.which("godot4")
    assert godot,"Godot executable not found"
    blender=shutil.which("blender")
    assert blender,"Blender executable not found"
    with tempfile.TemporaryDirectory(prefix="walkers-checks-") as profile:
        env=os.environ.copy()
        for key,folder in [("XDG_CONFIG_HOME","config"),("XDG_CACHE_HOME","cache"),("XDG_DATA_HOME","data")]:
            env[key]=str(Path(profile)/folder)
        def run(name,args,cwd=ROOT):
            result=subprocess.run(args,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=240)
            (REPORTS/(name+".log")).write_text(result.stdout)
            errors,network_limitations=classify_errors(result.stdout,options.allow_editor_socket_errors and name=="import")
            if network_limitations:limitations[name]=network_limitations
            if result.returncode or errors:
                print(result.stdout[-5000:])
                raise RuntimeError(f"{name} failed: exit={result.returncode}, errors={errors[:3]}")
            print("PASS",name,flush=True)
        run("import",[godot,"--headless","--editor","--path",str(ROOT),"--import"])
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(run,f"runtime_{rate}",[godot,"--headless","--path",str(ROOT),"--fixed-fps",str(rate),"--script","tests/runtime_test.gd","--","--rate=60",f"--render-rate={rate}"]) for rate in [30,60,120]]
            for future in futures:future.result()
        run("controls",[godot,"--headless","--path",str(ROOT),"--fixed-fps","60","--script","tests/controls.gd"])
        run("presentation",[godot,"--headless","--path",str(ROOT),"--fixed-fps","120","--script","tests/presentation_test.gd"])
        run("articulation",[godot,"--headless","--path",str(ROOT),"--fixed-fps","120","--script","tests/articulation_test.gd"])
        run("extensibility",[godot,"--headless","--path",str(ROOT),"--fixed-fps","60","--script","tests/extensibility.gd"])
        run("blender_source",[blender,"--background","source/character.blend","-noaudio","--python-exit-code","1","--python","tools/validate_blender.py"])
        run("contact_mechanics",[blender,"--background","source/character.blend","-noaudio","--python-exit-code","1","--python","tools/validate_contact_mechanics.py"])
        run("contact_export",[sys.executable,"tools/validate_contact_export.py"])
        run("assets",[sys.executable,"tools/validate_assets.py"])
        run("previews",[sys.executable,"tools/validate_previews.py"])
        run("comparison",[sys.executable,"tools/validate_motion_comparison.py"])
        pack=Path(profile)/"Walkers.pck"
        run("pack_export",[godot,"--headless","--path",str(ROOT),"--export-pack","Linux Desktop",str(pack)])
        run("pack_runtime",[godot,"--headless","--main-pack",str(pack),"--fixed-fps","60","--quit-after","120"],cwd=profile)
    summary={"status":"pass","godot":"4.7.2","blender":"5.2.2","render_rates":[30,60,120],"physics_rate":60,
             "assets":json.loads((REPORTS/"asset_validation.json").read_text()),
             "previews":json.loads((REPORTS/"preview_validation.json").read_text()),
             "extensibility":json.loads((REPORTS/"extensibility.json").read_text()),"runtime":{}}
    summary["controls"]=json.loads((REPORTS/"controls.json").read_text())
    summary["environment_limitations"]=limitations
    summary["presentation"]=json.loads((REPORTS/"presentation.json").read_text())
    summary["articulation"]=json.loads((REPORTS/"articulation.json").read_text())
    summary["comparison"]=json.loads((REPORTS/"comparison_validation.json").read_text()) if (REPORTS/"comparison_validation.json").exists() else {}
    summary["contact_mechanics"]=json.loads((REPORTS/"contact_mechanics.json").read_text())
    summary["contact_mechanics"].pop("sampled_clips", None)
    summary["blender_source"]=json.loads((REPORTS/"blender_validation.json").read_text())
    summary["contact_export"]=json.loads((REPORTS/"contact_export_validation.json").read_text())
    summary["exported_pack"]={"export":"pass","standalone_start":"pass","original_project_directory_used":False}
    table=[]
    for rate in [30,60,120]:
        report=json.loads((REPORTS/f"runtime_p60_r{rate}.json").read_text())
        summary["runtime"][str(rate)]={"failures":report["failures"],"cases":[{k:v for k,v in case.items() if k not in ["samples","worst","full_mesh_worst"]} for case in report["results"]]}
        for case in report["results"]:
            if case["name"] in ["walk","jog"]:
                table.append(f"| {rate} | {case['name']} | {case['mean_speed_after_settle']:.4f} | {case['support_drift_max_m']*100:.5f} | {case['full_mesh_penetration_m']*100:.4f} |")
    (REPORTS/"validation_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    report_text="""# 検証結果

Godot 4.7.2 / Blender 5.2.2。物理60Hz、描画30・60・120fpsで検証。

## 定速・接地

| 描画fps | モーション | 実速度 m/s | 支持点ずれ 最大cm | 足部メッシュ貫通 最大cm |
|---|---|---|---|---|
"""+"\n".join(table)+"""

支持点ずれは、前フレームの支持位置に対応する同じ皮膚上の材質点を、骨ウェイトで前後の最終姿勢に変形させ、その水平変位を全面接地区間で積算した値です。つま先が曲がるため、足首に固定した剛体点では代用しません。支持領域やアンカー移動で区間をリセットしません。旧メタデータに材質点の情報がない場合は従来の足首基準点で計測します。貫通はGLBから独立に読み出した足部の全検証頂点を8物理フレームごとにスキニングし、地面への垂直貫通と壁への水平貫通を検査。接地補正用サンプルについては毎物理フレームでも検査しています。姿勢とワールド変換は同じSkeleton評価時点で取得しています。

## シナリオ

待機、歩行、ジョギング、歩行→ジョギング→停止、180度反転、90度転換、発進中断、壁、25度斜面の上り下り、15cm段差の上り下り、40cm段差の通行止め、階段両側面の擦り付け・角からの離脱・入力解放・反転を実行しました。全描画fpsで全シナリオ合格です。斜面の足固定精度は平地の2cm基準とは分けて生値を記録しています。

カメラの右ドラッグと移動の同時操作、360度旋回、俯仰角・ズーム制限、フォーカス喪失、カメラ衝突、無入力待機、Space無反応、入力変更への応答はcontrols.jsonに記録しています。

## アセットと拡張

GLBの15モーション、変化するチャンネルの60fpsベイク、周期境界、男性体型用公式CC0ターゲットを含む同梱原本12ファイルのSHA-256を検証しました。追加歩容Resourceと公開APIによる4.2m/s移動、接地イベント、無効入力の停止も確認しました。追加歩容テストはJogを複製した試験専用動作であり、製品用ダッシュモーションの品質検証ではありません。

Blenderソースも開き直し、15 Action、実寸、非変形の編集用コントロール、FK/IKの足位置・回転・膝位置の一致を検査しています。Idleは全193フレーム・全57骨の姿勢不変を検査し、歩行・ジョギングは全フレームで上体の傾き、上腕の外転、実際の足軌道幅、足の交差、膝の前向き、ジョギングの足首角度変化を計測しています。骨盤と頭部の上下幅は6cm以内、最大上下速度0.80m/s以内、隣接ベイクフレームの変位2cm以内、周期端の速度差0.30m/s以内という演出上の基準で検査し、頭の上下動が完全固定されていないことも確認しています。接地曲線の半周期交互性、浮遊、支持領域の変化も検査しています。詳細はblender_validation.jsonに記録しています。

Linux Export PresetからPCKを生成し、元プロジェクトと異なる空の作業ディレクトリで起動しました。モデル・アニメーション・JSONを含む書き出し後のデータ読み込みにも成功しています。

## 足部と胴体の幾何検証

Blenderの評価済み変形メッシュで、踵・前足部・つま先の固定材質点パッチを毎60Hzフレーム追跡しました。接触順序・支持期間・踵が上がり前足部が残る時間、足首とつま先の相対角、荷重後の膝伸展と離地後の回収、骨盤三軸と背骨・胸郭の相対運動を検査しています。接地ラベルやIK重みから接触したと推定せず、床との実距離2mm以内を接触判定に用います。周期の接地開始・支持期間は足部全体の評価済み下側皮膚から求め、踵・前足部・つま先の固定パッチの接触時刻と区別します。固定パッチ間にある関節付近の接触が抜けても、支持期間が途中で切れないようにしています。床反力・筋力・推進力は計測していません。詳細と全サンプルはcontact_mechanics.json、変更前の測定はcontact_mechanics_before.jsonを参照してください。

## 画像

各33ポーズの横長PNG45枚、各視点に分離した全モーションGIF45本、実動作GIF、スローGIFをデコードし、サイズ、空白、周期境界、周期全体の等位相サンプルと25fpsの再生時間、全GIFフレームを検査しました。非周期GIFは320msの無地リセット区間を含みます。個別フレームは生成・検証用の一時データであり、納品には含めません。

表示補間は最終IK姿勢を含む前後の物理スナップショットで検査し、描画中にIKや接地イベントが再実行されないことを確認しました。参考値との比較では、元モーションの足・膝・手・骨盤の周期内速度変化、骨盤の山谷、胸郭基準の腕振り、肘屈曲変化、区分曲線の接続を検査しました。実測の変化はmotion_curve_comparison.jsonに記録しています。

つま先と胴体の局所姿勢を、接地補正前のアニメーションと最終IK姿勢で比較しました。足首の傾斜補正や表示補間によって、制作したつま先・背骨・胸郭の動きが消えないことを確認しています。接地重みを開始しきい値の前後へ揺らす試験でも、離地しきい値へ下がるまで接地イベントが再発行されないことを確認しました。詳細はarticulation.jsonを参照してください。

詳細と計測値はvalidation_summary.json、runtime_p60_r*.json、presentation.json、blender_validation.json、asset_validation.json、preview_validation.jsonを参照してください。
"""
    report_text=report_text.replace("## シナリオ\n",posture_report(summary)+"## シナリオ\n")
    (REPORTS/"VALIDATION.md").write_text(report_text)
    print("ALL_CHECKS_PASSED",flush=True)

if __name__=="__main__":main()

