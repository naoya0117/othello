#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/select.h>
#include <signal.h>
#include <ctype.h>
#include <stdarg.h>  /* va_listのため追加 */

#define PLAYERS 2
#define BUFFER_SIZE 1024
#define BOARD_SIZE 8
#define INITIAL_CLIENT_CAPACITY 10
#define SERVER_PORT 10000
#define DEBUG 1  // デバッグモード (1: 有効, 0: 無効)

/* ---- 型定義 ---- */
typedef enum { EMPTY, BLACK, WHITE } Cell;

typedef struct {
    Cell cells[BOARD_SIZE][BOARD_SIZE];
    int  current_turn;   /* 0: BLACK, 1: WHITE */
    int  winner;         /* -1: none, 0: BLACK, 1: WHITE */
} GameState;

typedef struct {
    int  socket;
    int  is_player;
    int  player_number;  /* 0: BLACK, 1: WHITE, -1: spectator */
} Client;

typedef struct {
    Client *array;
    size_t  size;
    size_t  capacity;
} ClientArray;

/* ---- グローバル ---- */
static ClientArray *g_clients  = NULL;
static int          g_server_fd = -1;
static GameState    g_state;
static int          g_connected_players = 0;
static int          g_game_in_progress  = 0;

/* 方向 (8 近傍) */
static const int DIRECTIONS[8][2] = {
    {-1, -1}, {-1, 0}, {-1, 1},
    { 0, -1},          { 0, 1},
    { 1, -1}, { 1, 0}, { 1, 1}
};

/* ---- ヘルパ ---- */
static void cleanup_resources(void);

static void debug_print(const char *fmt, ...) {
    if (!DEBUG) return;

    va_list args;
    va_start(args, fmt);
    fprintf(stderr, "[DEBUG] ");
    vfprintf(stderr, fmt, args);
    fprintf(stderr, "\n");
    va_end(args);
}

static void sigint_handler(int sig) {
    (void)sig;
    cleanup_resources();
    puts("\n[INFO] サーバーを終了します");
    exit(EXIT_SUCCESS);
}

static ssize_t safe_send(int sock, const void *buf, size_t len) {
    return send(sock, buf, len, MSG_NOSIGNAL);
}

static ClientArray *create_client_array(void) {
    ClientArray *ca = calloc(1, sizeof(ClientArray));
    if (!ca) return NULL;

    ca->array = calloc(INITIAL_CLIENT_CAPACITY, sizeof(Client));
    if (!ca->array) { free(ca); return NULL; }

    ca->capacity = INITIAL_CLIENT_CAPACITY;
    return ca;
}

static int expand_client_array(ClientArray *ca) {
    size_t new_cap = ca->capacity * 2;
    Client *tmp   = realloc(ca->array, new_cap * sizeof(Client));
    if (!tmp) return 0;
    ca->array   = tmp;
    ca->capacity = new_cap;
    return 1;
}

static int add_client(ClientArray *ca, Client c) {
    if (ca->size >= ca->capacity && !expand_client_array(ca)) return 0;
    ca->array[ca->size++] = c;
    return 1;
}

static void remove_client(ClientArray *ca, size_t idx) {
    if (idx >= ca->size) return;
    close(ca->array[idx].socket);
    if (idx < ca->size - 1)
        memmove(&ca->array[idx], &ca->array[idx+1], (ca->size-idx-1)*sizeof(Client));
    ca->size--;
}

static int is_valid_pos(int r,int c){ return r>=0 && r<BOARD_SIZE && c>=0 && c<BOARD_SIZE; }

/* ---- JSONパース関数 ---- */
static int parse_json_move(const char *json, int *row, int *col) {
    char *row_str = strstr(json, "\"row\"");
    char *col_str = strstr(json, "\"col\"");

    if (!row_str || !col_str) {
        debug_print("JSONパース失敗: キーが見つかりません");
        return 0;
    }

    // row値の抽出
    row_str += 5; // "row":の後
    while (*row_str && (*row_str == ' ' || *row_str == ':')) row_str++; // スペース・コロンをスキップ
    if (!isdigit(*row_str) && *row_str != '-') {
        debug_print("JSONパース失敗: row値が数値ではありません");
        return 0;
    }
    *row = atoi(row_str);

    // col値の抽出
    col_str += 5; // "col":の後
    while (*col_str && (*col_str == ' ' || *col_str == ':')) col_str++; // スペース・コロンをスキップ
    if (!isdigit(*col_str) && *col_str != '-') {
        debug_print("JSONパース失敗: col値が数値ではありません");
        return 0;
    }
    *col = atoi(col_str);

    debug_print("JSONパース成功: row=%d, col=%d", *row, *col);
    return 1;
}

/* ---- ゲームロジック ---- */
static void init_game_state(GameState *s){
    for(int i=0;i<BOARD_SIZE;i++)
        for(int j=0;j<BOARD_SIZE;j++) s->cells[i][j]=EMPTY;
    s->cells[3][3]=WHITE; s->cells[3][4]=BLACK;
    s->cells[4][3]=BLACK; s->cells[4][4]=WHITE;
    s->current_turn=0; s->winner=-1;
}

static int can_flip_dir(GameState *s,int r,int c,int dr,int dc){
    Cell me = s->current_turn==0?BLACK:WHITE;
    Cell opp= s->current_turn==0?WHITE:BLACK;
    int rr=r+dr, cc=c+dc, found=0;
    while(is_valid_pos(rr,cc)){
        if(s->cells[rr][cc]==opp){ found=1; }
        else if(s->cells[rr][cc]==me && found) return 1;
        else break;
        rr+=dr; cc+=dc;
    }
    return 0;
}

static int is_valid_move(GameState *s,int r,int c){
    if(!is_valid_pos(r,c)||s->cells[r][c]!=EMPTY) return 0;
    for(int i=0;i<8;i++) if(can_flip_dir(s,r,c,DIRECTIONS[i][0],DIRECTIONS[i][1])) return 1;
    return 0;
}

static void flip_dir(GameState *s,int r,int c,int dr,int dc){
    Cell me = s->current_turn==0?BLACK:WHITE;
    Cell opp= s->current_turn==0?WHITE:BLACK;
    int rr=r+dr, cc=c+dc;
    int pos[BOARD_SIZE][2], n=0;
    while(is_valid_pos(rr,cc)&& s->cells[rr][cc]==opp){ pos[n][0]=rr; pos[n][1]=cc; n++; rr+=dr; cc+=dc; }
    if(is_valid_pos(rr,cc)&& s->cells[rr][cc]==me){ for(int i=0;i<n;i++) s->cells[pos[i][0]][pos[i][1]]=me; }
}

static void make_move(GameState *s,int r,int c){
    s->cells[r][c]= s->current_turn==0?BLACK:WHITE;
    for(int i=0;i<8;i++) if(can_flip_dir(s,r,c,DIRECTIONS[i][0],DIRECTIONS[i][1])) flip_dir(s,r,c,DIRECTIONS[i][0],DIRECTIONS[i][1]);
}

static int has_valid_moves(GameState *s){
    for(int i=0;i<BOARD_SIZE;i++)
        for(int j=0;j<BOARD_SIZE;j++)
            if(is_valid_move(s,i,j)) return 1;
    return 0;
}

static void switch_turn(GameState *s){ s->current_turn ^= 1; }

static int count_stones(GameState *s, Cell c){
    int cnt=0; for(int i=0;i<BOARD_SIZE;i++) for(int j=0;j<BOARD_SIZE;j++) if(s->cells[i][j]==c) cnt++; return cnt;
}

/*
 * current_turn を書き換えずにゲーム終了判定
 */
static int check_game_over(GameState *s){
    if(has_valid_moves(s)) return 0; /* 現手番に合法手がある */
    int orig = s->current_turn;
    s->current_turn = 1 - orig;
    int opp_has = has_valid_moves(s);
    s->current_turn = orig;
    if(opp_has) return 0;            /* 相手に手がある */
    /* 両者打てない → 終局 */
    int b=count_stones(s,BLACK), w=count_stones(s,WHITE);
    s->winner = (b>w)?0:(w>b)?1:-1;
    return 1;
}

/* ---- JSON ---- */
static size_t calc_json_buffer(void){ return 512; }

static char *create_json_state(const GameState *s){
    size_t sz = calc_json_buffer();
    char *buf = malloc(sz); if(!buf) return NULL;
    int p=0;
    p+=snprintf(buf+p, sz-p, "{\"board\":[");
    for(int i=0;i<BOARD_SIZE;i++){
        p+=snprintf(buf+p, sz-p,"[");
        for(int j=0;j<BOARD_SIZE;j++)
            p+=snprintf(buf+p, sz-p, "%d%s", s->cells[i][j], (j<BOARD_SIZE-1)?",":"");
        p+=snprintf(buf+p, sz-p, "]%s", (i<BOARD_SIZE-1)?",":"");
    }
    p+=snprintf(buf+p, sz-p, "],\"current_turn\":%d,\"winner\":%d}", s->current_turn, s->winner);
    return buf;
}

static void send_error(int sock,const char *msg){
    char err[BUFFER_SIZE];
    snprintf(err,sizeof(err),"{\"error\":\"%s\"}",msg);
    debug_print("エラー送信: %s", err);
    safe_send(sock,err,strlen(err));
}

static void broadcast_state(const GameState *s){
    char *json = create_json_state(s);
    if(!json) return;
    debug_print("盤面状態ブロードキャスト: %s", json);
    for(size_t i=0;i<g_clients->size;){
        if(safe_send(g_clients->array[i].socket,json,strlen(json))<0){
            perror("send");
            /* 切断処理 */
            remove_client(g_clients,i);
            if(g_clients->array && g_clients->size==0) i=0; else continue; /* index stays */
        }else i++;
    }
    free(json);
}

static void handle_game_over(void){
    int b=count_stones(&g_state,BLACK);
    int w=count_stones(&g_state,WHITE);
    char msg[BUFFER_SIZE];
    snprintf(msg,sizeof(msg),"{\"type\":\"game_over\",\"winner\":%d,\"black_score\":%d,\"white_score\":%d}",g_state.winner,b,w);
    debug_print("ゲーム終了メッセージ: %s", msg);
    for(size_t i=0;i<g_clients->size;i++) safe_send(g_clients->array[i].socket,msg,strlen(msg));
    printf("[INFO] ゲーム終了: winner=%d B=%d W=%d\n",g_state.winner,b,w);
    sleep(10);
    /* 盤面リセットし次対局準備 */
    init_game_state(&g_state);
    g_game_in_progress = 0;
}

/* ---- クライアント切断 ---- */
static void handle_client_disconnect(size_t idx){
    Client c = g_clients->array[idx];
    if(c.is_player){
        g_connected_players--;
        printf("[INFO] プレイヤー %d 切断\n",c.player_number);
        if(g_game_in_progress){
            g_game_in_progress = 0;
            g_state.winner = 1 - c.player_number;
            handle_game_over();
        }
    }else{
        puts("[INFO] 観戦者切断");
    }
    remove_client(g_clients,idx);
}

/* ---- クライアントメッセージ ---- */
static int process_client_message(size_t idx,const char *msg){
    Client *c = &g_clients->array[idx];
    if(!c->is_player){
        send_error(c->socket,"あなたはプレイヤーではありません");
        return 0;
    }
    if(c->player_number != g_state.current_turn){
        send_error(c->socket,"あなたのターンではありません");
        return 0;
    }

    int r, cpos;
    debug_print("受信メッセージ: %s", msg);

    // 修正: より柔軟なJSONパース
    if(!parse_json_move(msg, &r, &cpos)){
        send_error(c->socket,"無効な入力フォーマット");
        return 0;
    }

    if(!is_valid_pos(r,cpos)){
        send_error(c->socket,"無効な座標です");
        return 0;
    }
    if(!is_valid_move(&g_state,r,cpos)){
        send_error(c->socket,"その場所には置けません");
        return 0;
    }

    debug_print("有効な手を受信: row=%d, col=%d, プレイヤー=%d", r, cpos, c->player_number);
    make_move(&g_state,r,cpos);

    /* ターン交代 */
    switch_turn(&g_state);
    if(!has_valid_moves(&g_state)){
        /* 相手に手が無ければパス → 自分のターンに戻す */
        debug_print("相手の手がないためパス");
        switch_turn(&g_state);
    }

    if(check_game_over(&g_state)) handle_game_over();
    return 1;
}

/* ---- リソースクリーンアップ ---- */
static void cleanup_resources(void){
    if(g_clients){
        for(size_t i=0;i<g_clients->size;i++) close(g_clients->array[i].socket);
        free(g_clients->array); free(g_clients); g_clients=NULL;
    }
    if(g_server_fd>=0) close(g_server_fd);
}

/* ---- main ---- */
int main(void){
    signal(SIGINT,sigint_handler);

    g_clients = create_client_array();
    if(!g_clients){ fputs("client array alloc fail\n",stderr); return EXIT_FAILURE; }
    init_game_state(&g_state);

    /* ソケット準備 */
    g_server_fd = socket(AF_INET,SOCK_STREAM,0);
    if(g_server_fd<0){ perror("socket"); return EXIT_FAILURE; }
    int opt=1; setsockopt(g_server_fd,SOL_SOCKET,SO_REUSEADDR,&opt,sizeof(opt));

    struct sockaddr_in addr={0}; addr.sin_family=AF_INET; addr.sin_addr.s_addr=INADDR_ANY; addr.sin_port=htons(SERVER_PORT);
    if(bind(g_server_fd,(struct sockaddr*)&addr,sizeof(addr))<0){ perror("bind"); cleanup_resources(); return EXIT_FAILURE; }
    if(listen(g_server_fd,16)<0){ perror("listen"); cleanup_resources(); return EXIT_FAILURE; }

    printf("[INFO] Reversi サーバー起動 – port %d\n",SERVER_PORT);

    fd_set readfds;

    while(1){
        FD_ZERO(&readfds);
        FD_SET(g_server_fd,&readfds);
        int maxsd=g_server_fd;
        for(size_t i=0;i<g_clients->size;i++){
            int sd=g_clients->array[i].socket;
            FD_SET(sd,&readfds);
            if(sd>maxsd) maxsd=sd;
        }
        if(select(maxsd+1,&readfds,NULL,NULL,NULL)<0){ if(errno==EINTR) continue; perror("select"); break; }

        /* 新規接続 */
        if(FD_ISSET(g_server_fd,&readfds)){
            int new_sd = accept(g_server_fd,NULL,NULL);
            if(new_sd<0){ perror("accept"); continue; }
            Client cli={.socket=new_sd,.is_player=0,.player_number=-1};
            if(!add_client(g_clients,cli)){ perror("add_client"); close(new_sd); continue; }
            size_t idx=g_clients->size-1; /* 追加した要素のインデックス */

            if(g_connected_players<PLAYERS){
                g_clients->array[idx].is_player=1;
                g_clients->array[idx].player_number=g_connected_players;
                g_connected_players++;

                char msg[128];
                snprintf(msg,sizeof(msg),"{\"type\":\"player_assigned\",\"player_number\":%d}",g_clients->array[idx].player_number);
                safe_send(new_sd,msg,strlen(msg));
                printf("[INFO] プレイヤー接続: %d\n",g_clients->array[idx].player_number);
                debug_print("プレイヤー割り当てメッセージ送信: %s", msg);

                /* 新規プレイヤーに現在盤面を送る */
                char *state_json = create_json_state(&g_state);
                if(state_json){
                    safe_send(new_sd,state_json,strlen(state_json));
                    debug_print("盤面状態送信: %s", state_json);
                    free(state_json);
                }
            }else{
                const char *spec="{\"type\":\"spectator_assigned\"}";
                safe_send(new_sd,spec,strlen(spec));
                puts("[INFO] 観戦者接続");
                debug_print("観戦者割り当てメッセージ送信");
                /* 盤面送信 */
                char *state_json=create_json_state(&g_state);
                if(state_json){
                    safe_send(new_sd,state_json,strlen(state_json));
                    debug_print("盤面状態送信: %s", state_json);
                    free(state_json);
                }
            }

            /* 全プレイヤー揃ったらゲーム開始メッセージ */
            if(g_connected_players==PLAYERS && !g_game_in_progress){
                g_game_in_progress=1;
                const char *start="{\"type\":\"game_start\"}";
                for(size_t i=0;i<g_clients->size;i++) safe_send(g_clients->array[i].socket,start,strlen(start));
                debug_print("ゲーム開始メッセージ送信");
                broadcast_state(&g_state);
            }
        }

        /* 既存クライアント */
        for(size_t i=0;i<g_clients->size;){
            int sd=g_clients->array[i].socket;
            if(FD_ISSET(sd,&readfds)){
                char buf[BUFFER_SIZE]={0};
                int n=read(sd,buf,sizeof(buf));
                if(n<=0){
                    handle_client_disconnect(i);
                    continue; /* idx stays same after removal */
                }
                buf[n]='\0';
                if(process_client_message(i,buf)) broadcast_state(&g_state);
            }
            i++;
        }
    }

    cleanup_resources();
    return 0;
}