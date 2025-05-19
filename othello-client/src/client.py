import pygame
import socket
import json
import threading
import time
import sys
import os

# サーバー設定
SERVER_PORT = 10000
BUFFER_SIZE = 4096

# ゲーム表示設定
WINDOW_WIDTH = 920
WINDOW_HEIGHT = 600
BOARD_SIZE = 8
CELL_SIZE = 60
BOARD_MARGIN = 50
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 128, 0)
DARKGREEN = (0, 100, 0)
LIGHTGREEN = (144, 238, 144)
GRAY = (128, 128, 128)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
TRANSPARENT = (0, 0, 0, 128)

# デバッグモード
DEBUG = False


class ReversiClient:
    def __init__(self):
        # ネットワーク関連
        self.socket = None
        self.connected = False
        self.receive_thread = None

        # ゲーム状態
        self.player_number = -1  # -1: 未割り当て/観戦者, 0: 黒, 1: 白
        self.is_spectator = True
        self.board = [[0 for _ in range(BOARD_SIZE)]
                      for _ in range(BOARD_SIZE)]
        self.current_turn = 0  # 0: 黒, 1: 白
        self.game_status = "not_started"  # not_started, waiting, playing, ended
        self.winner = -1  # -1: 未決着, 0: 黒勝ち, 1: 白勝ち

        # メッセージとエラー表示
        self.message = ""
        self.message_timer = 0
        self.error = ""
        self.error_timer = 0

        # Pygame初期化
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption("リバーシクライアント")

        # 日本語フォント設定
        self.load_japanese_font()

        self.clock = pygame.time.Clock()

        # 実行状態
        self.running = True

        # 最後のクリック位置記録用
        self.last_click_pos = None

        # デバッグログ
        self.debug_log = []

    def debug_print(self, message):
        """デバッグメッセージを出力"""
        if DEBUG:
            print(f"[DEBUG] {message}")
            self.debug_log.append(message)
            if len(self.debug_log) > 10:  # 最大10行保持
                self.debug_log.pop(0)

    def load_japanese_font(self):
        """日本語フォントを読み込む"""
        try:
            # フォントパスを試行
            font_paths = [
                # Windows フォント
                "C:/Windows/Fonts/meiryo.ttc",
                "C:/Windows/Fonts/msgothic.ttc",
                "C:/Windows/Fonts/YuGothic.ttc",
                # Mac フォント
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
                "/System/Library/Fonts/AppleGothic.ttf",
                # Linux フォント
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            ]

            # フォントを探索して使用
            for path in font_paths:
                if os.path.exists(path):
                    self.font = pygame.font.Font(path, 24)
                    self.big_font = pygame.font.Font(path, 36)
                    if DEBUG:
                        print(f"日本語フォントを読み込みました: {path}")
                    return

            # SysFont でフォールバック
            # 最終的なフォールバック：日本語が表示できない可能性がある
            if DEBUG:
                print("警告: 日本語フォントが見つかりませんでした。一部のテキストが正しく表示されない可能性があります。")
            self.font = pygame.font.SysFont(None, 24)
            self.big_font = pygame.font.SysFont(None, 36)

        except Exception as e:
            if DEBUG:
                print(f"フォント読み込みエラー: {e}")
            # エラー時のフォールバック
            self.font = pygame.font.SysFont(None, 24)
            self.big_font = pygame.font.SysFont(None, 36)

    def connect_to_server(self, ip, port):
        """サーバーに接続"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, port))
            self.connected = True
            self.set_message("サーバーに接続しました")
            self.debug_print(f"サーバー接続成功: {ip}:{port}")
            return True
        except Exception as e:
            self.set_error(f"接続エラー: {str(e)}")
            self.debug_print(f"接続エラー: {str(e)}")
            return False

    def start(self):
        """メインループを開始"""
        if not self.connected:
            self.set_error("サーバーに接続されていません")
            return

        # 受信スレッド開始
        self.receive_thread = threading.Thread(target=self.receive_loop)
        self.receive_thread.daemon = True
        self.receive_thread.start()

        # メインゲームループ
        while self.running:
            self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(30)

        # クリーンアップ
        self.cleanup()

    def receive_loop(self):
        """メッセージ受信ループ（別スレッド）"""
        buffer = ""
        while self.connected and self.running:
            try:
                data = self.socket.recv(BUFFER_SIZE).decode()
                if not data:
                    self.handle_disconnection()
                    break

                buffer += data
                self.debug_print(f"受信データ: {data}")

                # 複数のJSONメッセージが連結している可能性があるので分割処理
                while buffer:
                    try:
                        message = json.loads(buffer)
                        self.debug_print(f"処理メッセージ: {json.dumps(message)}")
                        self.process_message(message)
                        buffer = ""
                        break
                    except json.JSONDecodeError:
                        # 完全なJSONでない場合は次回に持ち越し
                        try:
                            # 途中まで処理できるか試す
                            pos = buffer.find("}{")
                            if pos != -1:
                                message = json.loads(buffer[:pos+1])
                                self.debug_print(
                                    f"部分メッセージ処理: {json.dumps(message)}")
                                self.process_message(message)
                                buffer = buffer[pos+1:]
                            else:
                                # 不完全なメッセージは次回に持ち越し
                                self.debug_print(f"不完全なメッセージ保留: {buffer}")
                                break
                        except Exception as e:
                            self.debug_print(f"部分メッセージ処理エラー: {str(e)}")
                            # 不完全なメッセージは次回に持ち越し
                            break

            except Exception as e:
                self.set_error(f"受信エラー: {str(e)}")
                self.debug_print(f"受信エラー: {str(e)}")
                self.handle_disconnection()
                break

    def process_message(self, message):
        """受信したメッセージを処理"""
        if "type" in message:
            self.handle_type_message(message)
        elif "board" in message:
            self.handle_board_message(message)
        elif "error" in message:
            self.handle_error_message(message)
        else:
            self.debug_print(f"不明なメッセージフォーマット: {json.dumps(message)}")

    def handle_type_message(self, message):
        """タイプメッセージの処理"""
        msg_type = message["type"]
        self.debug_print(f"タイプメッセージ: {msg_type}")

        if msg_type == "player_assigned":
            self.player_number = message["player_number"]
            self.is_spectator = False
            player_str = "黒（先手）" if self.player_number == 0 else "白（後手）"
            self.set_message(f"あなたはプレイヤー {player_str} です")
            self.game_status = "waiting"
            self.debug_print(f"プレイヤー割り当て: {player_str}")

        elif msg_type == "spectator_assigned":
            self.is_spectator = True
            self.player_number = -1
            self.set_message("あなたは観戦者です")
            self.game_status = "waiting"
            self.debug_print("観戦者として割り当てられました")

        elif msg_type == "game_start":
            self.game_status = "playing"
            self.set_message("ゲームが開始されました")
            self.debug_print("ゲーム開始")

        elif msg_type == "game_over":
            self.game_status = "ended"
            self.winner = message["winner"]
            self.debug_print(f"ゲーム終了: 勝者={self.winner}")

            # 次のゲームのためにwaiting状態に戻す
            self.game_status = "waiting"

    def handle_board_message(self, message):
        """盤面メッセージの処理"""
        self.board = message["board"]
        self.current_turn = message["current_turn"]
        self.debug_print(f"盤面更新: 現在の手番={self.current_turn}")

        if message["winner"] != -1:
            self.winner = message["winner"]
            self.game_status = "ended"
            self.debug_print(f"ゲーム終了: 勝者={self.winner}")

    def handle_error_message(self, message):
        """エラーメッセージの処理"""
        error_text = message["error"]
        self.set_error(error_text)
        self.debug_print(f"エラーメッセージ: {error_text}")

    def handle_disconnection(self):
        """切断処理"""
        if self.connected:
            self.connected = False
            self.set_error("サーバーから切断されました")
            self.debug_print("サーバーから切断されました")

    def handle_events(self):
        """イベント処理"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            # マウスクリック処理
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_pos = pygame.mouse.get_pos()
                self.last_click_pos = mouse_pos
                self.debug_print(f"マウスクリック: {mouse_pos}")

                # ボード上の位置を計算
                board_x = (mouse_pos[0] - BOARD_MARGIN) // CELL_SIZE
                board_y = (mouse_pos[1] - BOARD_MARGIN) // CELL_SIZE

                # ボード内のクリックか確認
                if (0 <= board_x < BOARD_SIZE and 0 <= board_y < BOARD_SIZE):
                    self.debug_print(
                        f"ボードセルクリック: row={board_y}, col={board_x}")

                    # 自分のターンの場合だけ入力を受け付ける
                    if (self.game_status == "playing" and
                        not self.is_spectator and
                            self.current_turn == self.player_number):

                        self.debug_print(f"手を送信: row={board_y}, col={board_x}")
                        self.send_move(board_y, board_x)  # row, colの順
                    else:
                        if self.game_status != "playing":
                            self.debug_print(f"ゲーム状態が無効: {self.game_status}")
                        elif self.is_spectator:
                            self.debug_print("観戦者は手を打てません")
                        else:
                            self.debug_print(
                                f"あなたの番ではありません: 現在の手番={self.current_turn}, あなたの番号={self.player_number}")
                            
            # デバッグ用のキー入力
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_w:  # "W"キーで黒の勝利
                    self.force_win(0)
                elif event.key == pygame.K_e:  # "E"キーで白の勝利
                    self.force_win(1)
                elif event.key == pygame.K_r:  # "R"キーで引き分け
                    self.force_win(-1)
                            
    def force_win(self, winner):
        """
        勝利を強制するデバッグ用メソッド。

        Args:
            winner (int): 勝者を指定 (-1: 引き分け, 0: 黒の勝利, 1: 白の勝利)
        """
        if self.game_status != "playing":
            self.debug_print("ゲームが進行中ではありません。勝利を強制できません。")
            return

        self.winner = winner
        self.game_status = "ended"

        if winner == 0:
            self.set_message("デバッグ: 黒の勝利を強制しました")
        elif winner == 1:
            self.set_message("デバッグ: 白の勝利を強制しました")
        else:
            self.set_message("デバッグ: 引き分けを強制しました")

        self.debug_print(f"勝利を強制: 勝者={self.winner}")
                            
    def show_winner_screen(self):
        """勝敗画面を表示"""
        self.screen.fill(GREEN)  # 背景を緑に設定

        # 勝者のメッセージを表示
        if self.winner == 0:
            winner_text = "黒の勝ち！"
        elif self.winner == 1:
            winner_text = "白の勝ち！"
        else:
            winner_text = "引き分け！"

        winner_surface = self.big_font.render(winner_text, True, WHITE)
        winner_rect = winner_surface.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 50))
        self.screen.blit(winner_surface, winner_rect)

        # 再戦または終了のメッセージ
        restart_text = "スペースキーで再戦 / ESCキーで終了"
        restart_surface = self.font.render(restart_text, True, WHITE)
        restart_rect = restart_surface.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 50))
        self.screen.blit(restart_surface, restart_rect)

        pygame.display.flip()

        # ユーザー入力を待つ
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    waiting = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:  # スペースキーで再戦
                        self.reset_game()
                        waiting = False
                    elif event.key == pygame.K_ESCAPE:  # ESCキーで終了
                        self.running = False
                        waiting = False

    def reset_game(self):
        """ゲームをリセット"""
        self.board = [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.board[3][3] = 2
        self.board[4][4] = 2
        self.board[3][4] = 1
        self.board[4][3] = 1
        self.current_turn = 0
        self.game_status = "playing"
        self.winner = -1
        self.set_message("新しいゲームを開始しました")

    def update(self):
        """状態更新"""
        # メッセージタイマー更新
        if self.message_timer > 0:
            self.message_timer -= 1

        # エラータイマー更新
        if self.error_timer > 0:
            self.error_timer -= 1

        # ゲーム終了時に勝敗画面遷移
        if self.game_status == "ended":
            self.show_winner_screen()

    def draw(self):
        """画面描画"""
        # 背景
        self.screen.fill(GREEN)

        # ボード
        self.draw_board()

        # ステータス情報
        self.draw_status()

        # メッセージ
        self.draw_message()

        # エラー
        self.draw_error()

        # 接続待ち表示
        if self.game_status == "waiting" and not self.is_spectator:
            self.draw_waiting_screen()

        # デバッグ情報
        if DEBUG:
            self.draw_debug_info()

        pygame.display.flip()

    def draw_debug_info(self):
        """デバッグ情報の表示"""
        # デバッグ情報の背景
        debug_rect = pygame.Rect(10, 340, 400, 150)
        debug_surface = pygame.Surface((400, 150), pygame.SRCALPHA)
        debug_surface.fill((0, 0, 0, 180))  # 半透明の黒
        self.screen.blit(debug_surface, debug_rect)

        # ゲーム状態の詳細表示
        state_text = self.font.render(
            f"状態: {self.game_status} | プレイヤー: {self.player_number} | 手番: {self.current_turn}", True, WHITE)
        self.screen.blit(state_text, (20, 350))

        # 最後のクリック位置表示
        if self.last_click_pos:
            click_text = self.font.render(
                f"最後のクリック: {self.last_click_pos}", True, WHITE)
            self.screen.blit(click_text, (20, 375))

        # デバッグログの表示
        y_pos = 400
        for i, log in enumerate(self.debug_log[-5:]):  # 最新の5件のみ表示
            log_text = self.font.render(
                str(log)[-60:] if len(str(log)) > 60 else str(log), True, WHITE)  # 長すぎる場合は末尾のみ
            self.screen.blit(log_text, (20, y_pos + i * 20))

    def draw_waiting_screen(self):
        """ゲーム開始待ち画面表示"""
        if self.connected:
            # 半透明オーバーレイ
            overlay = pygame.Surface(
                (WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 128))  # 半透明の黒
            self.screen.blit(overlay, (0, 0))

            # 待機メッセージ
            waiting_text = self.big_font.render("対戦相手を待っています...", True, WHITE)
            text_rect = waiting_text.get_rect(
                center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
            self.screen.blit(waiting_text, text_rect)

            # 補足情報
            info_text = self.font.render(
                "ゲームを開始するには2人のプレイヤーが必要です", True, WHITE)
            info_rect = info_text.get_rect(
                center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 50))
            self.screen.blit(info_text, info_rect)

    def draw_board2(self):
        # ボード背景
        board_rect = pygame.Rect(
            BOARD_MARGIN - 5,
            TOP_MARGIN - 5,
            CELL_SIZE * BOARD_SIZE + 10,
            CELL_SIZE * BOARD_SIZE + 10
        )
        pygame.draw.rect(self.screen, DARKGREEN, board_rect)

        # セルとコマの描画
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                # セル
                cell_rect = pygame.Rect(
                    BOARD_MARGIN + col * CELL_SIZE,
                    TOP_MARGIN + row * CELL_SIZE,
                    CELL_SIZE,
                    CELL_SIZE
                )
                pygame.draw.rect(self.screen, LIGHTGREEN, cell_rect)
                pygame.draw.rect(self.screen, BLACK, cell_rect, 1)

                # コマ
                if self.board[row][col] != 0:
                    center_x = BOARD_MARGIN + col * CELL_SIZE + CELL_SIZE // 2
                    center_y = TOP_MARGIN + row * CELL_SIZE + CELL_SIZE // 2
                    color = BLACK if self.board[row][col] == 1 else WHITE
                    radius = CELL_SIZE // 2 - 5
                    pygame.draw.circle(self.screen, color, (center_x, center_y), radius)

        # 座標表示
        for i in range(BOARD_SIZE):
            # 列番号
            col_text = self.font.render(str(i), True, BLACK)
            self.screen.blit(col_text, (BOARD_MARGIN + i * CELL_SIZE + CELL_SIZE // 2 - 5, TOP_MARGIN - 25))
            # 行番号
            row_text = self.font.render(str(i), True, BLACK)
            self.screen.blit(row_text, (BOARD_MARGIN - 25, TOP_MARGIN + i * CELL_SIZE + CELL_SIZE // 2 - 5))

        # 石数表示（左上・右下はそのまま）
        black_count, white_count = self.count_stones()
        if not self.is_spectator:
            if self.player_number == 0:
                my_count = black_count
                opp_count = white_count
                my_color = BLACK
                opp_color = WHITE
            else:
                my_count = white_count
                opp_count = black_count
                my_color = WHITE
                opp_color = BLACK

            # 左上：相手
            pygame.draw.circle(self.screen, opp_color, (60, 40), 25)
            opp_font = pygame.font.Font(None, 48)
            opp_text = opp_font.render(str(opp_count), True, BLACK if opp_color == WHITE else WHITE)
            self.screen.blit(opp_text, (95, 22))

            # 右下：自分
            pygame.draw.circle(self.screen, my_color, (WINDOW_WIDTH - 80, WINDOW_HEIGHT - 40), 25)
            my_font = pygame.font.Font(None, 48)
            my_text = my_font.render(str(my_count), True, BLACK if my_color == WHITE else WHITE)
            self.screen.blit(my_text, (WINDOW_WIDTH - 50, WINDOW_HEIGHT - 58))

    def draw_board(self):
        """ボードの描画"""
        # ボード背景
        board_rect = pygame.Rect(
            BOARD_MARGIN - 5,
            BOARD_MARGIN - 5,
            CELL_SIZE * BOARD_SIZE + 10,
            CELL_SIZE * BOARD_SIZE + 10
        )
        pygame.draw.rect(self.screen, DARKGREEN, board_rect)

        # セルとコマの描画
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                # セル
                cell_rect = pygame.Rect(
                    BOARD_MARGIN + col * CELL_SIZE,
                    BOARD_MARGIN + row * CELL_SIZE,
                    CELL_SIZE,
                    CELL_SIZE
                )
                pygame.draw.rect(self.screen, LIGHTGREEN, cell_rect)
                pygame.draw.rect(self.screen, BLACK, cell_rect, 1)

                # コマ
                if self.board[row][col] != 0:
                    center_x = BOARD_MARGIN + col * CELL_SIZE + CELL_SIZE // 2
                    center_y = BOARD_MARGIN + row * CELL_SIZE + CELL_SIZE // 2

                    color = BLACK if self.board[row][col] == 1 else WHITE
                    radius = CELL_SIZE // 2 - 5

                    pygame.draw.circle(self.screen, color,
                                       (center_x, center_y), radius)

        # 座標表示
        for i in range(BOARD_SIZE):
            # 列番号（0-7）
            col_text = self.font.render(str(i), True, BLACK)
            self.screen.blit(col_text, (BOARD_MARGIN + i *
                             CELL_SIZE + CELL_SIZE // 2 - 5, BOARD_MARGIN - 25))

            # 行番号（0-7）
            row_text = self.font.render(str(i), True, BLACK)
            self.screen.blit(row_text, (BOARD_MARGIN - 25,
                             BOARD_MARGIN + i * CELL_SIZE + CELL_SIZE // 2 - 5))


    def draw_status(self):
        """ステータス情報の描画"""
        # プレイヤー情報
        if not self.is_spectator:
            player_str = "あなた: " + \
                ("黒（先手）" if self.player_number == 0 else "白（後手）")
            player_text = self.font.render(player_str, True, BLACK)
            self.screen.blit(player_text, (550, 50))
        else:
            spectator_text = self.font.render("あなたは観戦者です", True, BLACK)
            self.screen.blit(spectator_text, (550, 50))

        # 現在の手番
        turn_str = "現在の手番: " + ("黒" if self.current_turn == 0 else "白")
        turn_text = self.font.render(turn_str, True, BLACK)
        self.screen.blit(turn_text, (550, 80))

        # 石の数
        black_count, white_count = self.count_stones()
        count_text = self.font.render(
            f"黒: {black_count}  白: {white_count}", True, BLACK)
        self.screen.blit(count_text, (550, 110))

        # ゲーム状態
        if self.game_status == "not_started":
            status_text = self.font.render("接続中...", True, BLACK)
            self.screen.blit(status_text, (550, 140))
        elif self.game_status == "waiting":
            status_text = self.font.render("ゲーム開始を待っています...", True, BLACK)
            self.screen.blit(status_text, (550, 140))
        elif self.game_status == "playing":
            if not self.is_spectator and self.current_turn == self.player_number:
                status_text = self.font.render("あなたの番です", True, BLUE)
                self.screen.blit(status_text, (550, 140))
            else:
                status_text = self.font.render("相手の手を待っています...", True, BLACK)
                self.screen.blit(status_text, (550, 140))
        elif self.game_status == "ended":
            if self.winner == -1:
                status_text = self.font.render("ゲーム終了 - 引き分け", True, BLACK)
            elif self.winner == 0:
                status_text = self.font.render("ゲーム終了 - 黒の勝ち", True, BLACK)
            else:
                status_text = self.font.render("ゲーム終了 - 白の勝ち", True, BLACK)
            self.screen.blit(status_text, (550, 140))

        # 接続状態
        conn_status = "接続中" if self.connected else "切断"
        conn_color = BLUE if self.connected else RED
        conn_text = self.font.render(f"サーバー: {conn_status}", True, conn_color)
        self.screen.blit(conn_text, (550, 200))

        # プレイヤー接続状況の表示
        if self.connected:
            # 1行目
            connection_label = self.font.render("プレイヤー接続状況:", True, BLACK)
            self.screen.blit(connection_label, (550, 230))
            # 2行目
            status_str = "2人目を待っています" if self.game_status == 'waiting' else "2人接続済み"
            status_color = BLUE if self.game_status == 'waiting' else GREEN
            connection_status = self.font.render(status_str, True, status_color)
            self.screen.blit(connection_status, (550, 260))

    def draw_message(self):
        """メッセージの描画"""
        if self.message and self.message_timer > 0:
            message_text = self.font.render(self.message, True, BLUE)
            self.screen.blit(message_text, (50, 550))

    def draw_error(self):
        """エラーメッセージの描画"""
        if self.error and self.error_timer > 0:
            error_text = self.font.render(self.error, True, RED)
            self.screen.blit(error_text, (50, 520))

    def set_message(self, text):
        """メッセージを設定"""
        self.message = text
        self.message_timer = 180  # 約6秒間表示

    def set_error(self, text):
        """エラーメッセージを設定"""
        self.error = text
        self.error_timer = 180  # 約6秒間表示

    def count_stones(self):
        """黒と白の石の数をカウント"""
        black = sum(row.count(1) for row in self.board)
        white = sum(row.count(2) for row in self.board)
        return black, white

    def send_move(self, row, col):
        """手を送信"""
        if not self.connected:
            self.set_error("サーバーに接続されていません")
            return

        # サーバーコードから期待されるJSONフォーマット
        message = {"row": row, "col": col}

        try:
            # JSONデータを送信（スペースなしに）
            json_str = json.dumps(message, separators=(',', ':'))  # スペースを省く
            self.debug_print(f"送信データ: {json_str}")
            self.socket.send(json_str.encode())
        except Exception as e:
            self.set_error(f"送信エラー: {str(e)}")
            self.debug_print(f"送信エラー: {str(e)}")
            self.handle_disconnection()

    def cleanup(self):
        """リソースの解放"""
        if self.socket and self.connected:
            try:
                self.socket.close()
            except:
                pass
        pygame.quit()


def main():
    """メイン関数"""
    args = sys.argv
    # サーバーIPをコマンドライン引数から取得
    # コマンドライン引数でサーバーIPを指定できるようにする
    server_ip = args[1] if len(args) > 1 else "127.0.0.1"
    if len(sys.argv) > 1:
        server_ip = sys.argv[1]

    print(f"リバーシクライアント - サーバーIP: {server_ip} ポート: {SERVER_PORT}")

    client = ReversiClient()

    # サーバー接続
    if not client.connect_to_server(server_ip, SERVER_PORT):
        print("サーバーに接続できません。終了します。")
        pygame.quit()
        return

    # メインゲームループ開始
    client.start()


if __name__ == "__main__":
    main()
