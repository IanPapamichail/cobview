       IDENTIFICATION DIVISION.
       PROGRAM-ID. GENDATA.
      *> Writes N binary CUSTOMER records plus a CSV with the same
      *> values, so the Python side can be checked against COBOL.
      *> Usage: gendata [count] [data-file] [csv-file]
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO WS-DATA-PATH
               ORGANIZATION IS SEQUENTIAL.
           SELECT CSV-FILE ASSIGN TO WS-CSV-PATH
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
           COPY CUSTOMER.
       FD  CSV-FILE.
       01  CSV-LINE                PIC X(200).
       WORKING-STORAGE SECTION.
       01  WS-DATA-PATH            PIC X(256) VALUE "customers.dat".
       01  WS-CSV-PATH             PIC X(256) VALUE "customers.csv".
       01  WS-COUNT                PIC 9(7)   VALUE 1000.
       01  WS-ARGC                 PIC 9(4)   COMP-5.
       01  WS-ARG                  PIC X(256).
       01  WS-I                    PIC 9(7)   COMP-5.
       01  WS-K                    PIC 9(4)   COMP-5.
       01  WS-TMP                  PIC S9(12) COMP-5.
       01  ED-ID                   PIC 9(6).
       01  ED-BAL                  PIC -9(7).99.
       01  ED-CRED                 PIC -9(5).99.
       01  ED-VISITS               PIC 9(4).
       01  ED-POINTS               PIC -9(9).
       01  ED-RATE                 PIC -9(5).9(6).
       01  ED-SPEND                PIC -9(5).99 OCCURS 3 TIMES.
       01  WS-PTR                  PIC 9(4)   COMP-5.

       PROCEDURE DIVISION.
       MAIN.
           ACCEPT WS-ARGC FROM ARGUMENT-NUMBER
           IF WS-ARGC >= 1
               ACCEPT WS-ARG FROM ARGUMENT-VALUE
               MOVE FUNCTION NUMVAL(WS-ARG) TO WS-COUNT
           END-IF
           IF WS-ARGC >= 2
               ACCEPT WS-DATA-PATH FROM ARGUMENT-VALUE
           END-IF
           IF WS-ARGC >= 3
               ACCEPT WS-CSV-PATH FROM ARGUMENT-VALUE
           END-IF

           OPEN OUTPUT CUST-FILE CSV-FILE
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > WS-COUNT
               PERFORM BUILD-RECORD
               IF WS-I = WS-COUNT
                   PERFORM EXTREME-RECORD
               END-IF
               WRITE CUSTOMER-REC
               PERFORM WRITE-CSV
           END-PERFORM
           CLOSE CUST-FILE CSV-FILE
           DISPLAY "GENDATA: wrote " WS-COUNT " records"
           STOP RUN.

       BUILD-RECORD.
           INITIALIZE CUSTOMER-REC
           MOVE WS-I TO CUST-ID ED-ID
           STRING "CUSTOMER " ED-ID DELIMITED BY SIZE
               INTO CUST-NAME
           END-STRING

           COMPUTE WS-TMP = FUNCTION MOD(WS-I * 1234567, 999999999)
           COMPUTE CUST-BALANCE = WS-TMP / 100
           IF FUNCTION MOD(WS-I, 3) = 0
               COMPUTE CUST-BALANCE = 0 - CUST-BALANCE
           END-IF

           COMPUTE WS-TMP = FUNCTION MOD(WS-I * 777, 9999999)
           COMPUTE CUST-CREDIT-LIM = WS-TMP / 100
           IF FUNCTION MOD(WS-I, 5) = 0
               COMPUTE CUST-CREDIT-LIM = 0 - CUST-CREDIT-LIM
           END-IF

           COMPUTE CUST-VISITS = FUNCTION MOD(WS-I * 7, 10000)

           COMPUTE CUST-POINTS =
               FUNCTION MOD(WS-I * 1000003, 999999999)
           IF FUNCTION MOD(WS-I, 2) = 0
               COMPUTE CUST-POINTS = 0 - CUST-POINTS
           END-IF

           COMPUTE CUST-RATE = WS-I / 8

           PERFORM VARYING WS-K FROM 1 BY 1 UNTIL WS-K > 3
               COMPUTE WS-TMP =
                   FUNCTION MOD(WS-I * WS-K * 313, 9999999)
               COMPUTE MON-SPEND(WS-K) = WS-TMP / 100
               IF FUNCTION MOD(WS-I + WS-K, 4) = 0
                   COMPUTE MON-SPEND(WS-K) = 0 - MON-SPEND(WS-K)
               END-IF
           END-PERFORM

           IF FUNCTION MOD(WS-I, 2) = 1
               SET CUST-ACTIVE TO TRUE
           ELSE
               SET CUST-INACTIVE TO TRUE
           END-IF

           COMPUTE CD-YYYY = 2000 + FUNCTION MOD(WS-I, 27)
           COMPUTE CD-MM   = 1 + FUNCTION MOD(WS-I, 12)
           COMPUTE CD-DD   = 1 + FUNCTION MOD(WS-I, 28).

       EXTREME-RECORD.
      *> Last record holds the limits of every numeric field.
           MOVE -9999999.99 TO CUST-BALANCE
           MOVE  99999.99   TO CUST-CREDIT-LIM
           MOVE  9999       TO CUST-VISITS
           MOVE -999999999  TO CUST-POINTS
           MOVE -99999.99   TO MON-SPEND(1)
           MOVE  99999.99   TO MON-SPEND(2)
           MOVE  0          TO MON-SPEND(3).

       WRITE-CSV.
           MOVE CUST-BALANCE    TO ED-BAL
           MOVE CUST-CREDIT-LIM TO ED-CRED
           MOVE CUST-VISITS     TO ED-VISITS
           MOVE CUST-POINTS     TO ED-POINTS
           MOVE CUST-RATE       TO ED-RATE
           PERFORM VARYING WS-K FROM 1 BY 1 UNTIL WS-K > 3
               MOVE MON-SPEND(WS-K) TO ED-SPEND(WS-K)
           END-PERFORM
           MOVE SPACES TO CSV-LINE
           MOVE 1 TO WS-PTR
           STRING ED-ID                          ","
                  FUNCTION TRIM(CUST-NAME)       ","
                  ED-BAL                         ","
                  ED-CRED                        ","
                  ED-VISITS                      ","
                  ED-POINTS                      ","
                  ED-RATE                        ","
                  ED-SPEND(1)                    ","
                  ED-SPEND(2)                    ","
                  ED-SPEND(3)                    ","
                  CUST-STATUS                    ","
                  CUST-DATE-N
               DELIMITED BY SIZE
               INTO CSV-LINE WITH POINTER WS-PTR
           END-STRING
           WRITE CSV-LINE.
