# Walkers — 人型ロコモーション

標準的な成人男性の実人体型マネキンで、歩行、ジョギング、発進・停止、踏み替え旋回を検証・再利用するGodotプロジェクトです。立位は肩や全身を揺らさない静止姿勢です。接地補正と、Blenderで編集できる15種類のモーションを収録しています。

姿勢、足の運び、荷重、腕振りを人の動きとして説明した[「自然な歩行と、ゆったりしたジョギングを読む」](docs/gait_reference.ja.md)を付属しています。研究論文・運動指導資料14件と接地映像へのリンクを記載し、このモデルの数値設定とは区別しています。


## 起動

1. ZIPを展開します。
2. Godot **4.7.2**で `project.godot` を開き、初回インポートを待ちます。
3. **F5**で起動します。モデル・モーション・マテリアルは同梱済みです。実行時にBlender、ネット接続、プラグイン、素材ダウンロードは必要ありません。

Blenderの編集・再出力は **5.2.2 LTS**で検証しています。Godotの新しいIK・周期同期APIを使うため、4.7系を対象にしています。

実行形式への書き出し用にLinux / WindowsのExport Presetも付属します。GodotのExport Templatesを導入すると書き出せます。実行用JSONを含め、Blenderソースや検証画像は除外する設定です。別プロジェクトで書き出す場合も、Exportの非リソースファイルに`addons/walkers/assets/*.json`を含めてください。

| 操作 | キーボード／マウス | ゲームパッド |
|---|---|---|
| 移動 | WASD、矢印 | 左スティック。倒し量で歩行からジョギングへ |
| ジョギング | Shiftを押しながら移動 | LB |
| カメラ回転 | 右ドラッグ | 右スティック |
| ズーム | ホイール | マウス併用 |
| 位置のリセット | R | キーボード併用 |
| ヘルプ表示 | F1 | — |

通常歩行は **1.4m/s**、ジョギングは **2.8m/s**。キャラクターは入力方向へ身体を向けます。通常起動では自動移動を行いません。右ドラッグは立位・移動中のどちらでも使え、カメラの上下角は−80〜+35度、距離は1.2〜8mです。自動的に進行方向へ戻さず、選んだ向きを保ちます。障害物に近づくとカメラの距離を縮めます。壁のすぐ手前では上半身の近接表示になるため、右ドラッグで見やすい方向へ回してください。

試験場には平地、20度斜面、15cmの連続段差、壁、40cmの上れない段差があります。移動システムの対応範囲は斜面25度以内・段差15cm以内です。

## 内容

| 場所 | 内容 |
|---|---|
| `addons/walkers/` | 再利用するモーター、設定、モデル、モーション、接地補正 |
| `demo/` | 入力アダプター、追従カメラ、試験場、表示UI |
| `source/character.blend` | 編集用のモデル・骨・FKアニメーション・足IK |
| `source/third_party/` | 使用したCC0素材、ライセンス、コミットとSHA-256の記録 |
| `docs/gait_reference.ja.md` | 人間向けの歩行・ジョギング解説、独自模式図、参考文献と映像リンク |
| `previews/index.html` | オフラインで開けるモーションギャラリー |
| `previews/sheets/` | 各モーション・視点の横一列33ポーズPNG、計45枚 |
| `previews/gifs/` | 視点別のモーションGIF45本と、Godot実動作の通常速度・スローGIF |
| `reports/` | アセット、実行、画像、パッケージの検証結果 |
| `tests/`、`tools/` | 再検証、生成、描画、梱包のスクリプト |

`.gdignore`によりBlenderソース・素材原本・プレビューをGodotのインポート対象から外しています。Godotは同梱GLBを使います。

連続ポーズ画像は一周期を32等分し、最初と終わりを含む33姿勢を間隔の狭い横一列へ並べます。周期モーションは左足接地から右足接地を経て次の左足接地までを収録します。GIFは境界の同一姿勢を二重再生せず、同じ一周期を反復します。生成途中の個別PNGは一時ファイルとして使い、一覧画像とGIFの生成・検査が成功した後に削除します。

## 別プロジェクトへの組み込み

`addons/walkers`フォルダを、同じ `res://addons/walkers` の位置へコピーします。`character.tscn`をゲームの3Dシーンへ配置してください。オートロード、エディタープラグイン、デモ側の入力設定は不要です。地形は衝突レイヤー1、キャラクターはレイヤー2を使います。

入力アダプターやAIから、毎フレームまたは移動意図を変えるタイミングで次を呼びます。

```gdscript
@onready var character: HumanoidMotor = $Humanoid

func _physics_process(_delta: float) -> void:
    # ワールド座標の方向。長さは正規化され、Y成分は無視されます。
    character.set_move_intent(Vector3.FORWARD, 1.4)

func stop() -> void:
    character.set_move_intent(Vector3.ZERO, 0.0)
```

移動意図は次の呼び出しまで保持されます。入力方向がゼロ、速度が負、NaNなどの無効な入力では停止します。速度の上限は設定済み歩容の最大速度です。

```gdscript
character.footstep.connect(func(side: StringName, point: Vector3, normal: Vector3):
    # 接地音、砂埃などをここに接続します。
    print(side, point, normal)
)
character.state_changed.connect(func(previous: StringName, current: StringName):
    print(previous, " -> ", current)
)
character.reset_at(Vector3(0, 0.02, 4), 0.0)
```

`actual_velocity`、`animator.state`、`animator.phase`、`animator.contacts`を参照できます。`footstep`は接地したタイミングで発火し、初期配置の待機姿勢では発火しません。

### 設定

`default_config.tres`を複製し、キャラクターの`config`へ割り当てます。シーンの準備時に複製されるため、複数キャラクターの実行中設定は共有されません。速度・加速度・減速・旋回速度・斜面・段差・足固定・骨盤補正量などを変更できます。構成や歩容の変更は起動前に行います。

**ストライド長と最高速度は別の値です。** `walk_stride_length=1.47m`、`jog_stride_length=1.96m`は、同梱モーションの1周期の進行距離です。速度だけを変える場合、ストライド長を変更しません。実移動距離から再生速度を合わせます。

### 動作の構成

`CharacterBody3D`が移動・衝突・加減速・旋回を担当し、`AnimationTree`が待機、発進、移動、停止、旋回をブレンドします。歩行とジョギングは1秒の正規化タイムラインを共有し、実移動速度から周期を進めます。壁で止まった場合もアニメーションが前進を続けないようにしています。

接地曲線から足裏支持点を固定し、地形に合わせて骨盤、足首、つま先の高さを補正します。骨盤の補正は支持脚から計算し、遊脚の高さによって身体が沈み込まないようにしています。`SkeletonModifier3D` → `TwoBoneIK3D` → 足の向きの補正を順に評価します。斜面・段差ではスキニング後の足裏形状も使って補正します。下り坂では歩幅を短くして周期を合わせ、脚の伸び切りを抑えます。段差上りは毎物理フレームの上・前・下方向のカプセル衝突検査と、直前方の歩ける接地面の検査で判断します。時間で支持を保持する仕組みは使わず、地形の形状から都度支持を確認し、描画位置だけをなめらかに追従させます。壁や上れない段差では足先の水平接触も補正します。

骨盤の揺れや体幹・腕振りはベイク済みアニメーションに含まれます。平面移動と全身の旋回角はモーターが担当し、Root Motionの二重適用を防いでいます。

## Blenderでの編集

`source/character.blend`を開き、`Humanoid`を選択します。MPFBをインストールしなくても、メッシュ、ウェイト、骨、Action、IKを編集できます。

| Action | 内容 |
|---|---|
| `Idle` | 揺れを加えない直立、3.2秒の静止クリップ |
| `Walk` | 歩行1周期、1.05秒、1.47m相当 |
| `Jog` | ジョギング1周期、0.7秒、1.96m相当 |
| `StartWalkL/R`、`StartJogL/R` | 踏み出し脚別の発進 |
| `StopWalkL/R`、`StopJogL/R` | 支持脚別の停止 |
| `Turn90L/R`、`Turn180L/R` | 左右90度・180度の踏み替え旋回 |

各Actionは0フレームから始まり、60fpsです。NLAトラックは書き出し用として収録し、通常編集ではミュートしています。Action Editorで対象Actionを選択し、再生範囲を0〜そのActionの終端へ合わせます（Walkは63、Jogは42、Idleは192）。変更前にActionを複製すると原本も残せます。ファイル内のText「START_HERE • Walkers」にも編集メモがあります。

### FK / 足IK

- `foot_ik_Left`、`foot_ik_Right`は0でベイク済みFK、1で編集用IKです。
- `CTRL_Foot_Left/Right`で足、`CTRL_Knee_Left/Right`で膝の向きを編集します。コントロールは各FKフレームの足位置へ一致させてあります。
- `contact_left/right`は接地重みの編集用カーブです。ゲーム用の重みは`motions.json`にも保存しています。
- `preview_root_motion=1`では旋回の全身回転を表示します。0ではGodotへ渡すインプレース姿勢を表示します。`preview_heading`の角度とモーターの旋回曲線が対応します。
- `REFERENCE • Quaternius CC0`コレクションには元リグを非表示で残しています。

### 編集後のGLB書き出し

生成スクリプトを再実行すると手編集内容が置き換わるため、手編集後は別名保存したファイルから書き出してください。

1. `foot_ik_Left/Right=0`、`preview_root_motion=0`にします。IKで編集した場合は、先に変形骨のVisual Keyingで動作をベイクします。
2. `Humanoid`と`Humanoid_CC0`だけを選択します。
3. NLAの各モーショントラックを有効にし、glTF 2.0 / GLB / Selected Objects / NLA Tracks / Sampling Step 1 / Deformation Bonesで書き出します。シーンは60fpsを維持します。
4. `addons/walkers/assets/humanoid.glb`を更新してGodotで再インポートします。ゲーム内の旋回角はRootに重ねて適用しません。
5. 接地タイミングや長さを変更した場合、`motions.json`の`duration`、`frames`、`contacts`、`support_regions`、`support_offsets`、`exit_phase`も更新します。`schema_version=3`の`support_offsets`は各フレームの左右の連続支持位置（足首に対するGodotのレスト骨格座標のメートル値）です。接地中は支持位置の移動をロールとして追跡し、支持部位名の変化で足固定を取り直しません。`support_regions`は各フレームの左右支持部位（`heel`、`sole`、`ball`、`toes`、`air`）です。モデル形状を変更した場合は、足首に対する各支持部位の位置を持つ`support_points`も新しい形状へ合わせます。旧形式でこれらがない場合は全面支持として読み込みます。

## 別Humanoidへの差し替え

GodotのAdvanced Importで`SkeletonProfileHumanoid`のBoneMapを設定し、名前とRest姿勢を標準化します。サンプル用に`humanoid_bone_map.tres`を同梱し、同梱GLBのインポート設定にも適用しています。肩・手指・足先を含むボーンの対応を確認してください。名前をそろえるだけではRest姿勢の違いを吸収できません。

1. メートル単位、スケール1、足裏が原点のTポーズに整え、アニメーションをリターゲットします。
2. `character.tscn`を継承または複製し、`Visual/Model`を交換します。Visual内に`Skeleton3D`と`AnimationPlayer`が1つずつ必要です。
3. `Hips`、`Left/RightUpperLeg`、`Left/RightLowerLeg`、`Left/RightFoot`が必要です。骨の長さやウェイトの品質も接地に影響します。
4. 設定の`character_height`を実寸へ変更します。カプセルの高さと半径も追従します。
5. `use_library_sole_height=false`にし、`sole_height`を足首から足裏までの距離にします。
6. 新モデル用のモーションメタデータを複製し、`support_points`と各フレームの`support_offsets`を新しい足の形状へ合わせます。連続支持位置をまだ作らない場合は、各クリップの`support_offsets`を削除すると旧形式の支持部位を使います。同梱マネキンの足裏形状を流用せず、新モデルの`sole_samples_file`を作ります。省略する場合は空文字にすると足首高さによる補正になり、メッシュ形状を使う追加補正が無効になります。
7. 新体型の歩幅に合わせてストライド長を調整し、斜面・段差・急停止を再検証します。

足裏データの生成例です。モデルはBlenderでZ-up・前方-Y、適用済みスケール、Humanoid標準ボーン名へ正規化してください。

```sh
blender -b replacement.blend -noaudio --python tools/export_sole_samples.py -- \
  --mesh=CharacterMesh --output=/absolute/path/replacement_soles.json
```

## ダッシュなどの追加

1. 同じ骨構成で周期モーションを用意し、左右の接地位相をWalk/Jogへ合わせます。
2. GLBにActionを追加し、`motions.json`へ周期長・サンプル数・接地曲線・支持部位と連続支持位置の変化を追加します。
3. 設定の`extra_gaits`へ`LocomotionGait` Resourceを追加します。`animation`、`speed`、`stride_length`を設定すると、ブレンド点、速度上限、接地曲線の混合に反映されます。
4. `transition_prefix=Jog`では既存のジョギング発進・停止を使います。専用の`StartSprintL/R`、`StopSprintL/R`などを加える場合、`transition_prefix=Sprint`とします。
5. 入力アダプターから追加速度を指定し、新しい歩容の停止距離・接地・旋回を確認します。

ジャンプ、戦闘、ストレイフ、移動足場、フル階段昇降モーション、ネット同期は初版の対象外です。

## 再生成・検証

必要なのはGodot、Blender、Python 3とPillowです。GIFの生成にFFmpegは使いません。60fps比較MP4の生成・検証にはFFmpegとffprobeも必要です。コマンドはプロジェクトのルートから実行します。

```sh
# 同梱原本から再生成。既存の手編集 .blend は別名保存してください。
blender -b --factory-startup -noaudio --python tools/build_character.py

# 同梱画像と同じWorkbench描画。個別PNGを一時生成します。
# 材質と照明も評価する場合は --workbench の代わりに --eevee を指定します。
blender -b source/character.blend -noaudio --python tools/render_previews.py -- --workbench
python3 tools/assemble_previews.py

# 実際のGLBの周期境界・ベイク間隔・原本ハッシュを検証。
python3 tools/validate_assets.py

# 一括検証：インポート、30/60/120fps、画像、ライセンス、結果の集約。
python3 tools/run_checks.py

# Godotの画面から20秒分の実動作フレームを保存。
godot --path . --resolution 960x600 --fixed-fps 25 -- --capture
python3 tools/assemble_runtime.py

# 配布用ZIPを作成。エディターキャッシュや生キャプチャは含めません。
python3 tools/package_release.py
```

`render_previews.py`は一時ディレクトリの既存PNGを再利用します。アニメーションを更新した場合は`--overwrite`を付けます。`--clips=Walk,Jog`で対象を絞れます。`assemble_previews.py`は横長一覧と視点別GIFを生成し、成功した入力フレームを削除します。生成時にBlenderの音声終了フックが停止する環境に対応し、ファイルの同期保存後にバッチプロセスを終了しています。

比較動画を作り直す場合は、比較元の保存済み `.blend` とその `motions.json` を指定します。旧版のモデル・個別画像は全成果物版へ重複同梱していません。

```sh
python3 tools/render_motion_comparison.py \
  --before /path/to/previous/character.blend \
  --before-metadata /path/to/previous/motions.json
python3 tools/validate_motion_comparison.py
```

素材原本を再取得する場合だけ`python3 tools/fetch_assets.py`を実行します。`source/third_party/manifest.json`に記録したコミットへ固定し、ファイル単位のSHA-256を保存します。通常の再生成と実行には通信しません。

### 検証の読み方

`reports/validation_summary.json`と`reports/VALIDATION.md`に結果をまとめています。実行テストはデモ入力やカメラを使わず、別シーンに配置したキャラクターの公開APIを呼びます。

- 平地のWalk/Jog：定速速度の誤差5%以内、全面接地中の支持点ずれ2cm以内、足裏貫通1cm以内。
- ループ：GLBに格納された先頭・終端の位置差5mm以内、回転差1度以内。定数チャンネルの最適化は許容し、変化するチャンネルのサンプリング間隔を検証します。
- 地形：壁、25度斜面の上下、15cm段差の上下、40cm段差の通行止め、階段両側面の擦り付け・離脱・入力解放・反転。接地補正用サンプルに加えて、GLBから独立に取得した足部メッシュ全検証頂点のスキニング結果も間引きフレームで検査します。
- 接地支持点の検査では、前フレームの支持位置を同じ足の材質点として前後の最終姿勢に適用し、その水平変位を全面接地区間で積算します。支持部位やアンカー位置の変化では計測をリセットしません。骨盤・膝・足首に補正限界を設けるため、斜面では平地と同じ足固定精度を保証する値ではありません。
- 編集用モデル：Idleの全フレーム・全骨の姿勢不変を検査し、歩行・ジョギングの全フレームで体幹、上腕、足軌道幅、膝の向き、足首の動きを計測します。骨盤・頭の上下幅6cm以内、上下速度0.80m/s以内、隣接フレーム変位2cm以内、周期境界の速度差0.30m/s以内を演出上の上限とし、頭を同じ高さに完全固定しないことも検査します。
- 操作：通常起動で22秒間無入力の静止、Space無反応、移動中の右ドラッグ、ズームと俯仰角、フォーカス喪失、カメラ障害物回避、旋回中の入力変更を確認します。
- 非周期モーションのGIFは、小さなreset表記を付けた320msの空白区間を挟んで反復します。周期GIFは一周期全体を等位相で直接描画し、32分割の静止画像を再利用しません。周期境界の姿勢は二重収録せず、最も近い25fpsの枚数へ丸めます（歩行1.05秒→26枚・1.04秒、ジョギング0.7秒→18枚・0.72秒）。位相間隔を均等に保ち、元周期と再生時間の比率をinventoryへ記録します。スローGIFは動作確認のため再生速度を下げています。

数値レポートとともに、正面・側面・斜めの姿勢、通常速度・スロー再生、発進直後の停止・反転・速度の切り替えを確認してください。

## ライセンス

コードは[MIT](LICENSE)。同梱キャラクター、元モーション、および新規モーション・レンダー画像・解説用SVGはCC0です。元素材の制作者、取得元、固定コミット、ライセンスは[THIRD_PARTY.md](THIRD_PARTY.md)を参照してください。参考文献の画像・映像は同梱せず、リンクから参照する構成です。


### 表示の補間と比較動画

移動・接地・接地イベントは60Hzの物理処理で評価し、表示は前後の最終IK姿勢を補間します。表示姿勢は物理計算へ戻さず、カメラも同じ表示位置を追います。表示の遅れは最大1物理フレームで、Rによるリセット時は履歴を消去します。

修正前後の実時間60fps比較動画は`previews/comparison`に収録します。歩行・ジョギングの正面・側面・斜めを通常速度と0.5倍速で比較できます。GIFは周期を等位相で採取して25fpsへ丸めるため、歩調の判定は実時間動画を使ってください。`inventory.json`に元の周期とGIFの再生時間・比率を記録します。
