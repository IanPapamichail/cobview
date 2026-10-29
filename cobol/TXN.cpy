      *> TXN.cpy - a transaction handed to APPLYTXN, and its outcome.
       01  TXN-REC.
           05  TXN-AMOUNT          PIC S9(7)V99 COMP-3.
           05  TXN-RESULT          PIC X.
               88  TXN-APPLIED     VALUE "Y".
               88  TXN-INACTIVE    VALUE "I".
               88  TXN-OVERFLOW    VALUE "O".
           05  TXN-COUNT           PIC 9(9) COMP-5.
