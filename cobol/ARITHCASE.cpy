      *> ARITHCASE.cpy - one arithmetic test case, shared by the COBOL
      *> reference program (ARITH.cbl) and the Python differential tests.
       01  ARITH-CASE.
           05  AC-OP               PIC X.
      *>       C = COMPUTE ... ON SIZE ERROR        (truncation)
      *>       N = COMPUTE without ON SIZE ERROR
      *>       A Z E U G L T P = COMPUTE ROUNDED MODE IS
      *>           NEAREST-AWAY-FROM-ZERO, NEAREST-TOWARD-ZERO,
      *>           NEAREST-EVEN, AWAY-FROM-ZERO, TOWARD-GREATER,
      *>           TOWARD-LESSER, TRUNCATION, PROHIBITED
           05  AC-SOURCE           PIC S9(12)V9(6) COMP-3.
           05  AC-FLAGS            PIC X(9).
      *>       one Y/N per target: did ON SIZE ERROR fire?
           05  AC-TARGETS.
               10  T-ZONED         PIC S9(5)V99.
               10  T-UZONED        PIC 9(5)V99.
               10  T-PACKED        PIC S9(3)V9 COMP-3.
               10  T-UPACKED       PIC 9(3) COMP-3.
               10  T-COMP          PIC S9(4) COMP.
               10  T-COMP5         PIC 9(4) COMP-5.
               10  T-SCOMP5        PIC S9(4) COMP-5.
               10  T-LONG          BINARY-LONG.
               10  T-SEP           PIC S9(6) SIGN LEADING SEPARATE.
