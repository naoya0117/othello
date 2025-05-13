import socket
import struct
import pygame
import sys

OTHELLO_ROW = 8
OTHELLO_COL = 8
PORT = 10000 
MESSAGE_LENGTH = 64  # 仮設定、必要に応じて調整
NAME_LENGTH = 20
NO_STONE = ' '
EMPTY = 0
BLACK = 'B'
WHITE = 'W'
CONN_REQ = 1
CONN_RES = 2
PUT_MY_STONE = 3
PUT_OPP_STONE = 4
WIDTH, HEIGHT = 640, 640

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

def initialize_board():
    board = [[NO_STONE for _ in range(OTHELLO_COL)] for _ in range(OTHELLO_ROW)]
    board[3][3] = BLACK
    board[4][4] = BLACK
    board[3][4] = WHITE
    board[4][3] = WHITE
    return board

def print_board(board):
    print('  ' + ' '.join(map(str, range(OTHELLO_COL))))
    print(' ' + '-' * (OTHELLO_COL * 2 + 1))
    for i, row in enumerate(board):
        print(str(i) + ''.join(f'|{cell}' for cell in row) + '|')
    print(' ' + '-' * (OTHELLO_COL * 2 + 1))

def count_flip_stone(turn, row, col, d_row, d_col, board):
    t_row, t_col = row + d_row, col + d_col
    if not (0 <= t_row < OTHELLO_ROW and 0 <= t_col < OTHELLO_COL):
        return 0
    if board[t_row][t_col] == turn or board[t_row][t_col] == NO_STONE:
        return 0
    flip = 0
    while 0 <= t_row < OTHELLO_ROW and 0 <= t_col < OTHELLO_COL:
        if board[t_row][t_col] == NO_STONE:
            return 0
        if board[t_row][t_col] == turn:
            return flip
        flip += 1
        t_row += d_row
        t_col += d_col
    return 0

def flip_stone(turn, row, col, d_row, d_col, board):
    t_row, t_col = row + d_row, col + d_col
    while 0 <= t_row < OTHELLO_ROW and 0 <= t_col < OTHELLO_COL:
        if board[t_row][t_col] == turn:
            break
        board[t_row][t_col] = turn
        t_row += d_row
        t_col += d_col

def flip(turn, row, col, board):
    board[row][col] = turn
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            if d_row == 0 and d_col == 0:
                continue
            if count_flip_stone(turn, row, col, d_row, d_col, board) > 0:
                flip_stone(turn, row, col, d_row, d_col, board)

def check_position(turn, row, col, board):
    if board[row][col] != NO_STONE:
        return 0
    count = 0
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            if d_row == 0 and d_col == 0:
                continue
            count += count_flip_stone(turn, row, col, d_row, d_col, board)
    return count

def make_connection(addr):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((addr, PORT))
    return sock

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
    cell_size = WIDTH // 8
    # 緑の背景
    screen.fill((0, 128, 0))
    # 盤の線
    for i in range(9):
        pygame.draw.line(screen, (0, 0, 0), (i*cell_size, 0), (i*cell_size, HEIGHT))
        pygame.draw.line(screen, (0, 0, 0), (0, i*cell_size), (WIDTH, i*cell_size))
    # 石を描く
    for row in range(8):
        for col in range(8):
            if board[row][col] != EMPTY:
                color = (0,0,0) if board[row][col]==BLACK else (255,255,255)
                center = (col*cell_size + cell_size//2, row*cell_size + cell_size//2)
                pygame.draw.circle(screen, color, center, cell_size//2 - 5)


def main():
    import argparse

    pygame.init()

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption('Othello')
    EMPTY = 0
    BLACK = 1
    WHITE = 2

    board = [[EMPTY for _ in range(8)] for _ in range(8)]
    board[3][3] = WHITE
    board[4][4] = WHITE
    board[3][4] = BLACK
    board[4][3] = BLACK

    draw_board(screen, board)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', required=True, help='Server address')
    parser.add_argument('-n', required=True, help='User name')
    args = parser.parse_args()

    srv_addr = args.s
    user_name = args.n

    if len(user_name) > 20:
        print("the length of the input user name must be less than 20 characters.")
        exit(0)

    print(f"server address: {srv_addr}")
    print(f"user name: {user_name}")

    sock = make_connection(srv_addr)
    mycolor = initialize_game(sock, user_name)
    board = initialize_board()

    turn = BLACK
    while True:
        print_board(board)
        if turn != mycolor:
            print("--- waiting for my turn ---")
            data = sock.recv(MESSAGE_LENGTH)
            m = Msg.deserialize(data)
            if m.type != PUT_OPP_STONE:
                print("received message does not contain an opponent stone info")
                exit(1)
            flip(turn, m.row, m.col, board)
            turn = mycolor
            continue

        print(f"My turn \"{mycolor}\"")
        row = int(input("input row(0-7): "))
        col = int(input("input col(0-7): "))
        print(f"(row, col)=({row},{col})")

        if check_position(turn, row, col, board) == 0:
            print(f"you cannot put your stone at ({row}, {col}).")
            continue

        m = Msg()
        m.type = PUT_MY_STONE
        m.name = user_name
        m.color = mycolor
        m.row = row
        m.col = col
        sock.sendall(m.serialize())
        flip(turn, row, col, board)

        turn = WHITE if turn == BLACK else BLACK

if __name__ == "__main__":
    main()
