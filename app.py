import streamlit as st
import pandas as pd
from streamlit.column_config import SelectboxColumn, NumberColumn, TextColumn
import openai
from openai import OpenAI
import os
import glob

# --- アプリの基本設定 ---
st.set_page_config(
    page_title="AI馬券プランナー",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- OpenAI APIキーの設定 ---
client = None
with st.sidebar:
    st.header("APIキー設定 (OpenAI)")
    
    # secretsから読み込むかどうかをユーザーに確認
    use_secrets = st.radio(
        "既存のAPIキーを読み込みますか？",
        ('はい', 'いいえ')
    )
    
    if use_secrets == 'はい':
        password = st.text_input(
            "パスワードを入力してください:",
            type="password"
        )
        
        if password == st.secrets.get("PASSWORD"):
            try:
                # Streamlit Community Cloudのsecretsから読み込む
                OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
                if OPENAI_API_KEY:
                    st.success("APIキーが設定されました。")
                else:
                    st.warning("secretsにAPIキーが設定されていません。")
            except (FileNotFoundError, AttributeError):
                OPENAI_API_KEY = ""
                st.warning("secretsからAPIキーを読み込めませんでした。")
        else:
            st.error("パスワードが正しくありません。")
            OPENAI_API_KEY = ""
    else:
        # ユーザーにAPIキーの入力を促す
        OPENAI_API_KEY = st.text_input(
            "OpenAI API Key を入力してください:",
            type="password",
            help="APIキーはOpenAIのプラットフォームで取得できます。"
        )
        if OPENAI_API_KEY:
            st.success("APIキーが入力されました。")
        else:
            st.warning("APIキーが未入力です。買い目提案機能は利用できません。")

# APIキーがあればクライアントを初期化
if OPENAI_API_KEY:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        st.error(f"OpenAIクライアントの初期化中にエラーが発生しました: {e}")
        st.warning("正しいAPIキーが設定されているか、ご確認ください。")
        client = None
else:
    st.info("サイドバーでOpenAI APIキーを設定してください。")


# --- CSVファイル選択機能 ---
def get_csv_files(directory="data"):
    """指定されたディレクトリ内のCSVファイル一覧を取得する"""
    if not os.path.isdir(directory):
        os.makedirs(directory)
        st.warning(f"「{directory}」フォルダを作成しました。ここにレースのCSVファイルを入れてください。")
        return []
    return glob.glob(os.path.join(directory, '*.csv'))

with st.sidebar:
    st.header("レース選択")
    csv_files = get_csv_files()
    if not csv_files:
        st.error("dataフォルダにCSVファイルが見つかりません。")
        st.stop() # ファイルがなければ処理を停止

    # ファイル名からレース名部分を抽出して表示
    # 例: 'data/2024_天皇賞(秋).csv' -> '2024: 天皇賞(秋)'
    race_options = [os.path.splitext(os.path.basename(f))[0].replace('_', ': ') for f in csv_files]
    selected_race_name = st.selectbox("予想するレースを選択してください:", race_options)
    
    # 選択されたレース名に対応するファイルパスを取得
    selected_csv_path = csv_files[race_options.index(selected_race_name)]


# --- セッションステートの管理 ---
# レースが変更されたら、過去の提案結果をリセット
if 'current_race' not in st.session_state or st.session_state.current_race != selected_race_name:
    st.session_state.current_race = selected_race_name
    st.session_state.suggested_bets_text = None
    st.session_state.allocation_text = None
    # data_editorをリセットするためにキーを変更する
    st.session_state.data_editor_key = f"horse_editor_{selected_race_name}"

# --- メイン処理 ---
try:
    horses_data_full = pd.read_csv(selected_csv_path)
    # ファイル名からレース名を取得
    race_name = selected_race_name.split('_')[0]
except Exception as e:
    st.error(f"CSVファイルの読み込み中にエラーが発生しました: {e}")
    st.stop()

try:
    horses_data = horses_data_full[["馬番", "馬名", "オッズ", "人気"]].copy()
except KeyError as e:
    st.error(f"CSVファイルに必要な列 ({e}) がありません。列名を確認してください: 馬番, 馬名, オッズ, 人気")
    st.stop()


st.title(f"AI馬券プランナー \n ## {race_name}")

印選択肢 = ["◎", "◯", "▲", "△", "無印"]
df = pd.DataFrame(horses_data)
df.insert(1, "印", "無印")

# --- データエディタ (印入力) ---
col1, col2 = st.columns([2, 1])
with col1:
    if st.session_state.get('device_type') == 'pc':
        width = [30, 20, 30, 20]
    else:
        width = [20, 20, 30, 20]
    st.subheader("印を入力してください")
    column_config = {
        "馬番": NumberColumn(label="馬番", disabled=True, width=width[0]
        ),
        "印": SelectboxColumn(
            label="印",
            options=印選択肢,
            required=True,
            default="無印",
            width=width[1],
            help="各馬に印を選択してください。"
        ),
        "馬名": TextColumn(label="馬名", disabled=True, width="midium"),
        "オッズ": NumberColumn(label="オッズ", format="%.1f倍", disabled=True, width=width[2]),
        "人気": NumberColumn(label="人気", disabled=True, width=width[3]),
    }
    edited_df = st.data_editor(
        df,
        column_config=column_config,
        hide_index=True,
        num_rows="fixed",
        key=st.session_state.data_editor_key,
        use_container_width=True,
    )

# --- 入力された印の表示 ---
with col2:
    st.subheader("あなたの予想印")
    has_marks = False
    marked_horses_summary = {mark: [] for mark in ["◎", "◯", "▲", "△"]}
    
    for _, row in edited_df.iterrows():
        if row["印"] in marked_horses_summary:
            has_marks = True
            marked_horses_summary[row["印"]].append(f"({row['馬番']}){row['馬名']}")

    for mark, horses in marked_horses_summary.items():
        if horses:
            st.write(f"**{mark}**: {', '.join(horses)}")

    if not has_marks:
        st.info("いずれかの馬に印を入力してください。")


# --- LLMによる買い目提案機能 (OpenAI) ---
st.subheader("🎯 AIによる買い目提案 (OpenAI)")

selected_model = "gpt-4o"

# 戦略選択肢の定義とUI
strategy_options = ["高配当狙い", "的中率重視", "初心者向け", "上級者向け", "バランス重視"]
default_strategy_index = strategy_options.index("バランス重視") if "バランス重視" in strategy_options else 0
selected_strategy = st.selectbox(
    "馬券購入の戦略を選択してください:",
    strategy_options,
    index=default_strategy_index,
    key="strategy_select"
)
st.write(f"選択された戦略: **{selected_strategy}**")

# セッションステートの初期化
if 'suggested_bets_text' not in st.session_state:
    st.session_state.suggested_bets_text = None
if 'show_bet_suggestion_details' not in st.session_state:
    st.session_state.show_bet_suggestion_details = False

if 'prompt_context_for_odds' not in st.session_state:
    st.session_state.prompt_context_for_odds = ""

if client and OPENAI_API_KEY:
    if st.button(f"AI ({selected_model}) に買い目を提案してもらう", disabled=not has_marks, key="get_bets_button"):
        if not has_marks:
            st.warning("買い目を提案するには、いずれかの馬に印を入力してください。")
        else:
            with st.spinner(f"AI ({selected_model}) が買い目を考えています... 🤔"):
                # 買い目提案用の prompt_context (印がついた馬のみ)
                bet_prompt_context = ""
                for index, row in edited_df.iterrows():
                    if row["印"] != "無印":
                        bet_prompt_context += f"{row['印']} : {row['馬名']} (馬番:{row['馬番']}, オッズ:{row['オッズ']:.1f}倍, {row['人気']}番人気)\n"
                        st.session_state.prompt_context_for_odds += f"馬番:{row['馬番']}, オッズ:{row['オッズ']:.1f}倍\n"

                system_prompt_bets = f"""あなたはプロの馬券師AIです。
"""
                user_prompt_bets = f"""以下の情報に基づいて、競馬の馬券のおすすめの買い方（券種と組み合わせ）を提案してください。
馬券は「単勝、複勝、ワイド、馬連、馬単、3連複、3連単」の中から選び、印・オッズ・戦略の指向に基づいた、現実的で一貫性のある買い方にしてください。

【各印の馬名、馬番、単勝オッズ、人気】
{bet_prompt_context}

【戦略指向】
{selected_strategy}

【ルール】
- 買い方の点数は10点以内を目安としますが、3連系の馬券で戦略上必要な場合はこの限りではありません。
- 各馬券種において現実的な構成としてください。
    - 単勝: ◎の馬を中心に、戦略によっては◯も検討。
    - 馬連・馬単: ◎の馬から印のついた馬（◯, ▲, △）への流しを基本とします。戦略に応じて相手の数を調整してください。
    - ワイド: ◎の馬から1～3頭程度への流しを基本とします。
    - 3連複: ◎の馬を軸としたフォーメーションを基本とします。軸1頭ながし（◎ - ◯▲△ - ◯▲△）、または軸2頭ながし（◎◯ - ▲△）などを戦略に応じて使い分けてください。
    - 3連単: ◎の馬を1着固定とするフォーメーションを基本とします（例: ◎ → ◯▲△ → ◯▲△その他）。
- 【戦略指向】で指定された戦略を最優先し、その戦略に合致するような券種選択と組み合わせの提案をしてください。
    - 高配当狙い: 点数を絞りつつ、人気薄の馬も絡めた3連単や馬単などを検討。
    - 的中率重視: ワイドや複勝、馬連で手堅く。相手を広めに取る。
    - 初心者向け: 分かりやすい券種（単勝、複勝、ワイド、馬連）を中心に、少点数で。
    - 上級者向け: 複雑なフォーメーションや、オッズの歪みを考慮した戦略的な買い方も示唆。
    - バランス重視: 的中と回収のバランスを考えた組み合わせ。
- 必ず出力フォーマットに従い、買い目のみを出力してください（金額は記載しないこと）。

【出力フォーマット】
券種ごとの買い目：
- 券種の名前1: 買い目の組み合わせ（馬番で記載）
- 券種の名前2: 買い目の組み合わせ（馬番で記載）
...
"""
                try:
                    st.session_state.show_bet_suggestion_details = True # デバッグ情報を表示するフラグ
                    response = client.chat.completions.create(
                        model=selected_model,
                        messages=[
                            {"role": "system", "content": system_prompt_bets},
                            {"role": "user", "content": user_prompt_bets}
                        ],
                        temperature=0.7
                    )
                    st.session_state.suggested_bets_text = response.choices[0].message.content
                except openai.APIError as e:
                    st.error(f"OpenAI APIからの応答取得中にエラーが発生しました (買い目提案): {e}")
                    st.session_state.suggested_bets_text = None
                except Exception as e:
                    st.error(f"予期せぬエラーが発生しました (買い目提案): {e}")
                    st.session_state.suggested_bets_text = None
    
    # 買い目提案のデバッグ情報表示 (ボタン押下時のみ表示)
    # if st.session_state.show_bet_suggestion_details and st.session_state.get('get_bets_button_clicked', True): # ボタンが押された後に表示
    #     with st.expander("買い目提案のデバッグ情報（クリックで展開）", expanded=False):
    #         st.text_area("システムプロンプト (買い目):", system_prompt_bets if 'system_prompt_bets' in locals() else "N/A", height=100, key="debug_system_prompt_bets")
    #         st.text_area("ユーザープロンプト (買い目):", user_prompt_bets if 'user_prompt_bets' in locals() else "N/A", height=150, key="debug_user_prompt_bets")

    # 買い目提案結果の表示
    if st.session_state.suggested_bets_text:
        st.markdown("--- \n ### AIによる買い目提案結果")
        st.markdown(st.session_state.suggested_bets_text)

        # --- 予算入力と資金配分機能 ---
        st.markdown("---")
        st.subheader("💰 予算に応じた資金配分提案")
        
        budget = st.number_input("馬券購入の総予算を入力してください (円):", min_value=0, value=1000, step=100, key="budget_input")

        if st.button(f"AI ({selected_model}) に資金配分を提案してもらう", key="get_allocation_button"):
            if budget <= 0:
                st.warning("予算は0より大きい値を入力してください。")
            elif budget % 100 != 0:
                st.warning("予算は100円単位で入力してください。")
            else:
                with st.spinner(f"AI ({selected_model}) が資金配分を考えています... 🤔"):
                    system_prompt_allocation = f"""あなたはプロの馬券師AIです。
"""
                    user_prompt_allocation = f"""以下の情報に基づいて、各買い目への具体的な資金配分を提案してください。
予算内で、できるだけ効果的な配分をお願いします。ただし、賭け金は100円単位で行ってください。
必ず出力フォーマットに従ってください。

【予算総額】
{budget}円

【AIによって提案された買い目】
{st.session_state.suggested_bets_text}

【買い目の馬の情報（馬番、オッズ）】
{st.session_state.prompt_context_for_odds} 

【出力フォーマット】
#### 資金配分提案 (総予算: {budget}円)

券種ごとの買い目と金額：
- 券種名1: 買い目1（賭け金円）, 買い目2（賭け金円）
- 券種名2: 買い目1（賭け金円）, 買い目2（賭け金円）
"""
                    try:
                        # with st.expander("資金配分デバッグ情報（クリックで展開）", expanded=False):
                        #     st.text_area("システムプロンプト (資金配分):", system_prompt_allocation, height=100, key="debug_system_prompt_allocation")
                        #     st.text_area("ユーザープロンプト (資金配分):", user_prompt_allocation, height=150, key="debug_user_prompt_allocation")

                        allocation_response = client.chat.completions.create(
                            model=selected_model, # 資金配分にも同じモデルを使用 (変更も可能)
                            messages=[
                                {"role": "system", "content": system_prompt_allocation},
                                {"role": "user", "content": user_prompt_allocation}
                            ],
                            temperature=0.5 # 資金配分は少し堅実な結果を期待
                        )
                        st.markdown("--- \n ### AIによる資金配分提案結果")
                        st.markdown(allocation_response.choices[0].message.content)
                    except openai.APIError as e:
                        st.error(f"OpenAI APIからの応答取得中にエラーが発生しました (資金配分): {e}")
                    except Exception as e:
                        st.error(f"予期せぬエラーが発生しました (資金配分): {e}")
    elif st.session_state.show_bet_suggestion_details and not st.session_state.suggested_bets_text : # 買い目提案ボタンが押されたが結果がない場合
        st.warning("AIによる買い目提案の取得に失敗しました。APIキーや設定を確認してください。")