import socket
import struct
import pygame
import sys

OTHELLO_ROW = 8
OTHELLO_COL = 8
PORT = 10000 
MESSAGE_LENGTH = 64  # 仮設定、必要に応じて調整
NAME_LENGTH = 20
EMPTY = 0
BLACK = 'B'
WHITE = 'W'
CONN_REQ = 1
CONN_RES = 2
PUT_MY_STONE = 3
PUT_OPP_STONE = 4
WIDTH, HEIGHT = 860, 640

test_cell = {
  "cells": [
    ["BLACK", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY"],
    ["EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY"],
    ["EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY"],
    ["EMPTY", "EMPTY", "EMPTY", "WHITE", "BLACK", "EMPTY", "EMPTY", "EMPTY"],
    ["EMPTY", "EMPTY", "EMPTY", "BLACK", "WHITE", "EMPTY", "EMPTY", "EMPTY"],
    ["EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY"],
    ["EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY"],
    ["EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY", "EMPTY"]
  ],
  "current_turn": "BLACK",
  "winner": None
}

DIRECTIONS = [
    (-1, 0),  # 上
    (1, 0),   # 下
    (0, -1),  # 左
    (0, 1),   # 右
    (-1, -1), # 左上
    (-1, 1),  # 右上
    (1, -1),  # 左下
    (1, 1)    # 右下
]

class Msg:
    def __init__(self):
        self.type = 0
        self.name = ''
        self.color = ''
        self.row = -1
        self.col = -1

    def serialize(self):
        name_bytes = self.name.encode('utf-8')[:NAME_LENGTH]
        name_bytes += b'\x00' * (NAME_LENGTH - len(name_bytes))
        return struct.pack('!B20sccBB', self.type, name_bytes, self.color.encode(), b'\x00', self.row, self.col)

    @classmethod
    def deserialize(cls, data):
        m = cls()
        m.type, name_bytes, color, _, m.row, m.col = struct.unpack('!B20sccBB', data)
        m.name = name_bytes.decode('utf-8').strip('\x00')
        m.color = color.decode('utf-8')
        return m
    
def set_username(screen):
    font = pygame.font.SysFont("meiryo", 32)
    input_box = pygame.Rect(200, 300, 400, 50)  # 入力ボックスの位置とサイズ
    color_inactive = pygame.Color('black')
    color_active = pygame.Color('dodgerblue2')
    color = color_inactive
    active = False
    text = ''
    done = False

    while not done:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                # 入力ボックスがクリックされたかを確認
                if input_box.collidepoint(event.pos):
                    active = not active
                else:
                    active = False
                color = color_active if active else color_inactive
            if event.type == pygame.KEYDOWN:
                if active:
                    if event.key == pygame.K_RETURN:
                        if len(text) > 20:
                            print("The length of the input user name must be less than 20 characters.")
                        else:
                            done = True
                    elif event.key == pygame.K_BACKSPACE:
                        text = text[:-1]
                    else:
                        text += event.unicode

        # 画面を更新
        screen.fill((128, 200, 128))  # 背景色
        txt_surface = font.render(text, True, pygame.Color('black'))
        screen.blit(txt_surface, (input_box.x + 10, input_box.y + 10))
        pygame.draw.rect(screen, color, input_box, 2)

        # メッセージを表示
        message = font.render("あなたの名前を入力してください。", True, pygame.Color('black'))
        screen.blit(message, (200, 250))

        pygame.display.flip()

    return text

    
def verification_username(user_name):
    if len(user_name) > 20:
        print("The length of the input user name must be less than 20 characters.")
        exit(0)
    
    print(f"user name: {user_name}")

def initialize_board():
    board = [['EMPTY' for _ in range(OTHELLO_COL)] for _ in range(OTHELLO_ROW)]
    board[3][3] = BLACK
    board[4][4] = BLACK
    board[3][4] = WHITE
    board[4][3] = WHITE
    return board


def initialize_game(sock, user_name):
    m = Msg()
    m.type = CONN_REQ
    m.name = user_name
    sock.sendall(m.serialize())
    data = sock.recv(MESSAGE_LENGTH)
    m = Msg.deserialize(data)
    if m.type != CONN_RES:
        print("initialize process is not done.")
        exit(1)
    print(f"{user_name} vs {m.name}")
    print(f"My color is {m.color}")
    return m.color


def draw_board(screen, board):
    cell_size = 640 // 8  # 盤のサイズを640に固定
    # 緑の背景
    screen.fill((128, 200, 128))

    # 盤の線
    for i in range(9):
        pygame.draw.line(screen, (0, 0, 0), (i * cell_size, 0), (i * cell_size, 640))
        pygame.draw.line(screen, (0, 0, 0), (0, i * cell_size), (640, i * cell_size))

    # 石を描く
    for row in range(8):
        for col in range(8):
            color = (0, 0, 0)  # デフォルトの色
            match (board[row][col]):
                case 'EMPTY':
                    continue  # 石を描画しない
                case 'B':
                    color = (0, 0, 0)  # 黒
                case 'W':
                    color = (255, 255, 255)  # 白
            center = (col * cell_size + cell_size // 2, row * cell_size + cell_size // 2)
            pygame.draw.circle(screen, color, center, cell_size // 2 - 5)

    # 右側の空間に文字列を描画
    font = pygame.font.SysFont("meiryo", 16)
    text = font.render("Your Turn", True, (0, 0, 0))
    screen.blit(text, (660, 20))  # 盤の右側に表示
    text2 = font.render("score: 黒 2 - 白 2", True, (0, 0, 0))
    screen.blit(text2, (660, 60))


#def upgrade_board(board, cells):
#    for row in range(OTHELLO_ROW):
#        for col in range(OTHELLO_COL):
#            if cells["cells"][row][col] != "EMPTY":
#                color = "B" if cells["cells"][row][col] == "B" else "W"
#                board[row][col] = color
#    return board

def upgrade_board(board, cells):
    for row in range(OTHELLO_ROW):
        for col in range(OTHELLO_COL):
            if cells["cells"][row][col] == "EMPTY":
                board[row][col] = "EMPTY"  # セルをクリア
            elif cells["cells"][row][col] == "BLACK":
                board[row][col] = "B"  # 黒石
            elif cells["cells"][row][col] == "WHITE":
                board[row][col] = "W"  # 白石
    return board

def place_stone(board, row, col, current_turn):
    if can_place_stone(board, row, col, current_turn):
        board[row][col] = current_turn
        flip_stones(board, row, col, current_turn)
        return True
    return False

def can_place_stone(board, row, col, current_turn):
    """
    指定されたセルに石を置けるかを判定する。

    Args:
        board (list): 現在の盤面
        row (int): 石を置く行
        col (int): 石を置く列
        current_turn (str): 現在のターン（"B" または "W"）

    Returns:
        bool: 石を置ける場合はTrue、それ以外はFalse
    """
    if board[row][col] != "EMPTY":
        return False

    opponent = "W" if current_turn == "B" else "B"

    for dr, dc in DIRECTIONS:
        r, c = row + dr, col + dc
        found_opponent = False

        while 0 <= r < OTHELLO_ROW and 0 <= c < OTHELLO_COL and board[r][c] == opponent:
            found_opponent = True
            r += dr
            c += dc

        if found_opponent and 0 <= r < OTHELLO_ROW and 0 <= c < OTHELLO_COL and board[r][c] == current_turn:
            return True

    return False

def flip_stones(board, row, col, current_turn):
    """
    石を置いた際に相手の石を挟んでひっくり返す処理を行う。

    Args:
        board (list): 現在の盤面
        row (int): 石を置く行
        col (int): 石を置く列
        current_turn (str): 現在のターン（"B" または "W"）

    Returns:
        bool: 少なくとも1つの石をひっくり返した場合はTrue、それ以外はFalse
    """
    opponent = "W" if current_turn == "B" else "B"
    flipped = False

    for dr, dc in DIRECTIONS:
        stones_to_flip = []
        r, c = row + dr, col + dc

        while 0 <= r < OTHELLO_ROW and 0 <= c < OTHELLO_COL and board[r][c] == opponent:
            stones_to_flip.append((r, c))
            r += dr
            c += dc

        if 0 <= r < OTHELLO_ROW and 0 <= c < OTHELLO_COL and board[r][c] == current_turn:
            for fr, fc in stones_to_flip:
                board[fr][fc] = current_turn
            if stones_to_flip:
                flipped = True

    return flipped


def main():
    import argparse

    pygame.init()

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption('Othello')

    board = initialize_board()
    draw_board(screen, board)
    pygame.display.update() 
    print(board)
    # print(pygame.font.get_fonts())  # 利用可能なフォント一覧を表示
    #username = set_username(screen)

    current_turn = "BLACK"
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:  # 左クリック
                x, y = event.pos
                cell_size = 640 // 8
                col = x // cell_size
                row = y // cell_size
                print("石を今から億")
                # 石を置く処理を関数で呼び出し
                if place_stone(board, row, col, current_turn):
                    current_turn = "WHITE" if current_turn == "BLACK" else "BLACK"
                print("石を置く")
            if event.type == pygame.QUIT:
                running = False
            #upgrade_board(board, test_cell)
            draw_board(screen, board)
            pygame.display.update() 


if __name__ == "__main__":
    main()
