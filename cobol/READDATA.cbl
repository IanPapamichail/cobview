       IDENTIFICATION DIVISION.
       PROGRAM-ID. READDATA.
      *> Reads CUSTOMER records and prints them as CSV, in the same
      *> format as GENDATA, so edits made from Python can be checked
      *> by COBOL itself.
      *> Usage: readdata data-file csv-file
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
       01  WS-DATA-PATH            PIC X(256).
       01  WS-CSV-PATH             PIC X(256).
       01  WS-EOF                  PIC X VALUE "N".
       01  WS-K                    PIC 9(4)   COMP-5.
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
           ACCEPT WS-DATA-PATH FROM ARGUMENT-VALUE
           ACCEPT WS-CSV-PATH FROM ARGUMENT-VALUE
           OPEN INPUT CUST-FILE OUTPUT CSV-FILE
           PERFORM UNTIL WS-EOF = "Y"
               READ CUST-FILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END PERFORM WRITE-CSV
               END-READ
           END-PERFORM
           CLOSE CUST-FILE CSV-FILE
           STOP RUN.

       WRITE-CSV.
           MOVE CUST-ID         TO ED-ID
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
