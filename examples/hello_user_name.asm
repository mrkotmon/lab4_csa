; ============================================================
;  hello_user_name.asm
;
;  Спрашивает имя, читает его через прерывания (trap),
;  затем выводит "Hello, <name>!"
;
;  Сохраняем имя в буфере name_buf как pstr (длина + символы).
;  Ввод заканчивается на '\n' (код 10).
; ============================================================

.equ IO_IN   2046
.equ IO_OUT  2047
.equ NEWLINE 10

.data
.org 0
        .word irq_handler           ; вектор прерывания

.org 100
prompt: .string "What is your name?\n"

.org 150
greet1: .string "Hello, "

.org 170
greet2: .string "!\n"

.org 200                            ; pstr-буфер для имени
name_buf: .word 0                   ; первое слово — длина
.org 201
name_chars: .word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0

.text
.org 1
_start:
        ; ---- 1) вывод prompt'а ----
        LI   R1, prompt
        JAL  R7, print_pstr

        ; ---- 2) инициализация буфера имени ----
        LI   R1, 0
        LI   R2, name_buf
        SW   R1, 0(R2)              ; name_buf.length = 0

        ; ---- 3) разрешить прерывания и ждать конца ввода ----
        EI
wait_loop:
        ; флаг конца ввода — обработчик кладёт 1 в done_flag
        LI   R1, done_flag
        LW   R2, 0(R1)
        BEQ  R2, R0, wait_loop      ; пока done_flag == 0 — крутимся
        DI

        ; ---- 4) вывод "Hello, " ----
        LI   R1, greet1
        JAL  R7, print_pstr

        ; ---- 5) вывод имени ----
        LI   R1, name_buf
        JAL  R7, print_pstr

        ; ---- 6) вывод "!\n" ----
        LI   R1, greet2
        JAL  R7, print_pstr
        HLT

; --------------------------------------------------------------------
;  print_pstr  --  печатает Pascal-string с адресом в R1.
;  Возврат: JR R7.   Использует R1, R2, R3, R4, R5.
; --------------------------------------------------------------------
print_pstr:
        LW   R2, 0(R1)              ; R2 = длина
        ADDI R3, R1, 1              ; R3 = указатель на первый символ
        LI   R4, 0                  ; R4 = i
        LI   R5, IO_OUT
pp_loop:
        BGE  R4, R2, pp_done
        LW   R1, 0(R3)
        SW   R1, 0(R5)
        ADDI R3, R3, 1
        ADDI R4, R4, 1
        JMP  pp_loop
pp_done:
        JR   R7

; --------------------------------------------------------------------
;  irq_handler  --  читает символ, добавляет к name_buf,
;  при '\n' выставляет done_flag.
; --------------------------------------------------------------------
irq_handler:
        LI   R1, IO_IN
        LW   R2, 0(R1)              ; R2 = новый символ
        LI   R3, NEWLINE
        BEQ  R2, R3, ih_finish
        ; добавить в буфер: ++name_buf.length, name_buf[len] = ch
        LI   R1, name_buf
        LW   R3, 0(R1)              ; R3 = текущая длина
        ADDI R4, R1, 1              ; R4 = указатель на name_chars
        ADD  R4, R4, R3             ; R4 += длина -> следующая позиция
        SW   R2, 0(R4)
        ADDI R3, R3, 1
        SW   R3, 0(R1)              ; обновить длину
        IRET
ih_finish:
        LI   R1, done_flag
        LI   R2, 1
        SW   R2, 0(R1)
        IRET

.data
.org 500
done_flag: .word 0
