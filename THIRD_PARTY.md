# 素材とライセンス

## MakeHuman / MPFB — CC0 1.0 Universal

- 制作者：MakeHuman Community / MakeHuman Team。
- 元データ：`makehumancommunity/mpfb2`の `base.obj`、ゲームエンジン用骨定義、頂点ウェイト、男性成人用の公式体型ターゲット。
- 公式ライセンス説明：<https://static.makehumancommunity.org/about/license.html>
- 元リポジトリ：<https://github.com/makehumancommunity/mpfb2>
- 改変：ヘルパーの除去、メートル単位への変換、身長1.78mの標準的な成人男性の体型への調整、Tポーズ化、ボーン名標準化、ウェイト4影響への正規化、マテリアルと編集用リグ、モーションの追加。
- 体型には`african-male-young`、`asian-male-young`、`caucasian-male-young`を各1/3、`universal-male-young-averagemuscle-averageweight`を1で適用しています。地域別ターゲットの混合は今回の中立的なマネキンを作る設定です。男性・若年成人・中間の筋肉量と体重を選び、特定個人や特定集団の標準値と主張するものではありません。
- 同梱するのはCC0のグラフィック用コア素材です。MPFB本体のGPLソースコードは同梱・転用していません。

## Universal Animation Library Standard — CC0 1.0 Universal

- 制作者：Quaternius。配布元は共同アニメーターとしてGonzalo Furnierもクレジットしています。
- 公式配布：<https://quaternius.itch.io/universal-animation-library>
- 公式紹介：<https://quaternius.com/packs/universalanimationlibrary.html>
- 取得した原本：2025-06-10配布のStandard FREE版のglTFを保存したJ-PonzoのCC0ミラー。
- ミラー：<https://github.com/J-Ponzo/gltf-universal-animation-library>
- 参照した原動作：`Idle_Loop`、`Walk_Loop`、`Jog_Fwd_Loop`。同梱の`Idle`は肩や全身を揺らさない直立へ作り直しています。
- 現行の動作は歩容の参考文献を踏まえ、姿勢・体幹・腕・脚のカーブを新規に組み立てています。Quaterniusの元リグと原動作は比較・編集の参考資料として保持しています。現行モーションの上半身へ原動作の回転をそのまま転用していません。
- 無料glTFからBlenderで編集用データを作成しています。有料Source版の `.blend` は使用していません。

原本のライセンス全文は `source/third_party/quaternius/LICENSE` に収録しています。同じCC0 1.0文面を `LICENSE-ASSETS.txt` にも同梱しています。

## Walkersで制作した内容

- GDScript、Python、シェーダー、設定・検証用コード：MIT（`LICENSE`）。
- 新規キャラクター加工、リグ、アニメーション、PNG、JPG、GIF、および`docs/images/`の解説用SVG：CC0 1.0 Universalとして提供します。
- ライセンス対象を除き、GodotやBlenderの実行バイナリ、追加アドオン、OSのフォントは配布物に含めません。

## 動作の参考文献

[自然な歩行と、ゆったりしたジョギングを読む](docs/gait_reference.ja.md)に、研究論文・運動指導資料7件の著者、年、題名、URL、参照箇所をまとめています。これらは動きを観察し説明するための文献です。各文献の画像、図表、映像の権利はそれぞれの権利者に帰属し、リンク先の資料をCC0として再配布するものではありません。元画像や動画は成果物へ同梱していません。解説の模式図はこのプロジェクトで新規制作しています。

## 固定バージョンとハッシュ

`source/third_party/manifest.json`に、原本ごとのリポジトリ、コミットSHA、取得URL、SHA-256を記録しています。`tools/validate_assets.py`で同梱原本のハッシュを再検証できます。

