      *> CUSTOMER.cpy - sample record layout for cobview tests.
      *> Mixes every storage type cobview v0.1 understands.
       01  CUSTOMER-REC.
           05  CUST-ID             PIC 9(6).
           05  CUST-NAME           PIC X(20).
           05  CUST-BALANCE        PIC S9(7)V99 COMP-3.
           05  CUST-CREDIT-LIM     PIC S9(5)V99.
           05  CUST-VISITS         PIC 9(4) COMP-5.
           05  CUST-POINTS         PIC S9(9) COMP.
           05  CUST-RATE           COMP-2.
           05  CUST-MONTHLY        OCCURS 3 TIMES.
               10  MON-SPEND       PIC S9(5)V99 COMP-3.
           05  CUST-STATUS         PIC X.
               88  CUST-ACTIVE     VALUE "A".
               88  CUST-INACTIVE   VALUE "I".
           05  CUST-DATE.
               10  CD-YYYY         PIC 9(4).
               10  CD-MM           PIC 99.
               10  CD-DD           PIC 99.
           05  CUST-DATE-N REDEFINES CUST-DATE
                                   PIC 9(8).
