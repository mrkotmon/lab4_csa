; hello.asm — статическая Pascal-строка из секции данных.
.equ IO_OUT 8188

.data
.org 1024
msg: .string "Hello, World!\n"

.text
.org 4
.entry _start
_start:
    LI   R1, msg
    LW   R2, 0(R1)       ; длина pstr
    ADDI R3, R1, 4       ; первый символ: следующее 32-битное слово
    LI   R4, 0
    LI   R5, IO_OUT
print_loop:
    BGE  R4, R2, done
    LW   R6, 0(R3)
    SW   R6, 0(R5)
    ADDI R3, R3, 4
    ADDI R4, R4, 1
    JMP  print_loop
done:
    HLT
