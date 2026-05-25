; ============================================================
;  sort.asm
;
;  Пользователь подаёт через ввод последовательность чисел,
;  разделённых пробелом.  Маркер конца ввода — '\0' (NUL).
;  Программа выводит числа в возрастающем порядке.
;
;  Внутреннее представление списка чисел — pstr-подобное:
;     numbers[0]   = количество чисел
;     numbers[1..] = сами числа
;
;  Это перекликается с pstr для строк: для всего, что
;  списочное, кладём длину перед содержимым.
;
;  Сортировка — простой выбором (selection sort).
; ============================================================

.equ IO_IN   2046
.equ IO_OUT  2047
.equ SPACE   32
.equ NEWLINE 10
.equ NULL    0
.equ ZERO    48              ; код '0'
.equ NINE    57

.data
.org 0
        .word irq_handler

.org 500
numbers: .word 0             ; numbers[0] = count
.org 501
nums_storage: .word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0

.org 600
cur_value: .word 0           ; собираем здесь текущее число
.org 601
collecting: .word 0          ; 1, если сейчас «внутри» числа
.org 602
done_flag: .word 0

.org 700
digits:   .word 0,0,0,0,0,0,0,0,0,0,0,0

.text
.org 1
_start:
        ; начать чтение
        LI   R1, numbers
        LI   R2, 0
        SW   R2, 0(R1)       ; count = 0
        EI
wait:
        LI   R1, done_flag
        LW   R2, 0(R1)
        BEQ  R2, R0, wait
        DI

        ; -- сортировка selection sort --
        LI   R1, numbers
        LW   R1, 0(R1)       ; R1 = N
        LI   R2, 0           ; i = 0
sort_outer:
        BGE  R2, R1, sort_done
        ADDI R3, R2, 1       ; j = i + 1
sort_inner:
        BGE  R3, R1, sort_inner_done
        ; сравниваем numbers[i+1] и numbers[j+1]
        LI   R4, nums_storage
        ADD  R5, R4, R2      ; addr_i
        ADD  R6, R4, R3      ; addr_j
        LW   R4, 0(R5)       ; arr[i]
        LW   R7, 0(R6)       ; arr[j]
        BLE  R4, R7, no_swap
        ; swap
        SW   R7, 0(R5)
        SW   R4, 0(R6)
no_swap:
        ADDI R3, R3, 1
        JMP  sort_inner
sort_inner_done:
        ADDI R2, R2, 1
        JMP  sort_outer
sort_done:
        ; -- печать --
        LI   R2, 0           ; i = 0
        LI   R7, numbers
        LW   R7, 0(R7)       ; R7 = N
print_outer:
        BGE  R2, R7, all_printed
        LI   R3, nums_storage
        ADD  R3, R3, R2
        LW   R6, 0(R3)       ; R6 = arr[i] — это печатает print_int
        ; сохраняем счётчик/предел в неприкосновенных регистрах
        ; (print_int использует R1..R5, не трогает R7).
        ; сохранять и восстанавливать i и N будем через память:
        LI   R3, save_i
        SW   R2, 0(R3)
        LI   R3, save_n
        SW   R7, 0(R3)
        JAL  R1, print_int
        LI   R3, save_i
        LW   R2, 0(R3)
        LI   R3, save_n
        LW   R7, 0(R3)
        ; пробел
        LI   R3, SPACE
        LI   R4, IO_OUT
        SW   R3, 0(R4)
        ADDI R2, R2, 1
        JMP  print_outer
all_printed:
        LI   R3, NEWLINE
        LI   R4, IO_OUT
        SW   R3, 0(R4)
        HLT

; -------- print_int (печатает R6) ---------
; вход:  R6 — число
; clobbers: R1..R5
; link: R1
print_int:
        LI   R3, 0
        LI   R4, digits
        LI   R5, 10
        BEQ  R6, R0, pi_zero
pi_extract:
        BEQ  R6, R0, pi_print
        MOD  R2, R6, R5
        DIV  R6, R6, R5
        ADDI R2, R2, 48
        SW   R2, 0(R4)
        ADDI R4, R4, 1
        ADDI R3, R3, 1
        JMP  pi_extract
pi_zero:
        LI   R2, 48
        SW   R2, 0(R4)
        ADDI R3, R3, 1
pi_print:
        LI   R2, IO_OUT
        LI   R5, digits
pi_loop:
        BEQ  R3, R0, pi_done
        ADDI R3, R3, -1
        ADD  R4, R5, R3
        LW   R4, 0(R4)
        SW   R4, 0(R2)
        JMP  pi_loop
pi_done:
        JR   R1

; ---------------- обработчик прерывания --------------------
; Читает один символ.  Если это цифра — добавляем в cur_value.
; Если пробел/перенос — фиксируем cur_value (если что-то собрано).
; Если '\0' — done_flag := 1.
irq_handler:
        LI   R1, IO_IN
        LW   R2, 0(R1)              ; R2 = символ
        LI   R3, NULL
        BEQ  R2, R3, ih_end
        ; цифра?
        LI   R3, ZERO
        BLT  R2, R3, ih_sep
        LI   R3, NINE
        BGT  R2, R3, ih_sep
        ; цифра: cur_value = cur_value*10 + (R2 - '0')
        LI   R1, cur_value
        LW   R3, 0(R1)
        LI   R4, 10
        MUL  R3, R3, R4
        LI   R4, ZERO
        SUB  R2, R2, R4
        ADD  R3, R3, R2
        SW   R3, 0(R1)
        LI   R1, collecting
        LI   R3, 1
        SW   R3, 0(R1)
        IRET
ih_sep:
        ; разделитель — фиксируем число, если собирали
        LI   R1, collecting
        LW   R3, 0(R1)
        BEQ  R3, R0, ih_skip
        LI   R1, cur_value
        LW   R4, 0(R1)              ; собранное число
        LI   R3, 0
        SW   R3, 0(R1)              ; cur_value = 0
        LI   R1, collecting
        SW   R3, 0(R1)              ; collecting = 0
        ; добавить число в массив
        LI   R1, numbers
        LW   R3, 0(R1)              ; R3 = count
        LI   R5, nums_storage
        ADD  R5, R5, R3
        SW   R4, 0(R5)
        ADDI R3, R3, 1
        SW   R3, 0(R1)
ih_skip:
        IRET
ih_end:
        ; зафиксировать незакрытое число, если есть
        LI   R1, collecting
        LW   R3, 0(R1)
        BEQ  R3, R0, ih_set_done
        LI   R1, cur_value
        LW   R4, 0(R1)
        LI   R1, numbers
        LW   R3, 0(R1)
        LI   R5, nums_storage
        ADD  R5, R5, R3
        SW   R4, 0(R5)
        ADDI R3, R3, 1
        SW   R3, 0(R1)
ih_set_done:
        LI   R1, done_flag
        LI   R3, 1
        SW   R3, 0(R1)
        IRET

.data
.org 800
save_i: .word 0
save_n: .word 0
