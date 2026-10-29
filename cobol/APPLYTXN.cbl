       IDENTIFICATION DIVISION.
       PROGRAM-ID. APPLYTXN.
      *> Business rule written in COBOL, called from Python with
      *> cobview.Program. It works directly on the caller's memory:
      *> a CUSTOMER record (often a memory-mapped file) and a TXN.
      *>   - inactive customers are refused           RETURN-CODE 4
      *>   - a balance that would overflow is refused RETURN-CODE 8
      *>   - otherwise the amount is posted, the visit counted, and
      *>     the running count (kept in WORKING-STORAGE) returned.
      *> Run totals live in EXTERNAL storage, which Python can watch
      *> by name with Program.external("TXN-STATS").
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-APPLIED              PIC 9(9) COMP-5 VALUE 0.
       01  TXN-STATS EXTERNAL.
           05  STAT-APPLIED        PIC 9(9) COMP-5.
           05  STAT-REJECTED       PIC 9(9) COMP-5.
           05  STAT-POSTED         PIC S9(11)V99 COMP-3.
       LINKAGE SECTION.
           COPY CUSTOMER.
           COPY TXN.
       PROCEDURE DIVISION USING CUSTOMER-REC TXN-REC.
           IF NOT CUST-ACTIVE
               SET TXN-INACTIVE TO TRUE
               ADD 1 TO STAT-REJECTED
               DISPLAY "APPLYTXN: customer " CUST-ID " is inactive"
               MOVE 4 TO RETURN-CODE
               GOBACK
           END-IF
           COMPUTE CUST-BALANCE = CUST-BALANCE + TXN-AMOUNT
               ON SIZE ERROR
                   SET TXN-OVERFLOW TO TRUE
                   ADD 1 TO STAT-REJECTED
                   DISPLAY "APPLYTXN: customer " CUST-ID
                           " balance would overflow"
                   MOVE 8 TO RETURN-CODE
                   GOBACK
           END-COMPUTE
           ADD 1 TO CUST-VISITS
           ADD 1 TO WS-APPLIED
           ADD 1 TO STAT-APPLIED
           ADD TXN-AMOUNT TO STAT-POSTED
           MOVE WS-APPLIED TO TXN-COUNT
           SET TXN-APPLIED TO TRUE
           MOVE 0 TO RETURN-CODE
           GOBACK.
