; hello_user_name.asm — ввод имени через trap, хранение как pstr.
.equ IO_IN  8184
.equ IO_OUT 8188
.equ LF     10

.data
.org 0
    .word irq_handler
.org 1024
question: .string "What is your name?\n"
greeting: .string "Hello, "
name:     .word 0
          .word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
suffix:   .string "!\n"

.text
.org 4
.entry _start
_start:
    LI  R1, question
    JAL R7, print_pstr
    EI
wait:
    JMP wait

irq_handler:
    LI  R1, IO_IN
    LW  R2, 0(R1)
    LI  R3, LF
    BEQ R2, R3, complete
    LI  R3, name
    LW  R4, 0(R3)       ; текущая длина
    MULI R5, R4, 4
    ADD  R5, R5, R3
    ADDI R5, R5, 4
    SW   R2, 0(R5)
    ADDI R4, R4, 1
    SW   R4, 0(R3)
    IRET
complete:
    DI
    LI  R1, greeting
    JAL R7, print_pstr
    LI  R1, name
    JAL R7, print_pstr
    LI  R1, suffix
    JAL R7, print_pstr
    HLT

; R1 = адрес Pascal-строки; порт вывода memory-mapped.
print_pstr:
    LW   R2, 0(R1)
    ADDI R3, R1, 4
    LI   R4, 0
    LI   R5, IO_OUT
pp_loop:
    BGE  R4, R2, pp_done
    LW   R6, 0(R3)
    SW   R6, 0(R5)
    ADDI R3, R3, 4
    ADDI R4, R4, 1
    JMP  pp_loop
pp_done:
    JR   R7
