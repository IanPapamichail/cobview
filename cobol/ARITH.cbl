       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
      *> Reference for cobview's COBOL arithmetic rules: stores
      *> AC-SOURCE into every target with the statement AC-OP names,
      *> one statement per target so each ON SIZE ERROR sets its own
      *> flag. Python calls this through cobview.Program and must
      *> produce the same bytes (tests/test_arithmetic.py).
       DATA DIVISION.
       LINKAGE SECTION.
           COPY ARITHCASE.
       PROCEDURE DIVISION USING ARITH-CASE.
           MOVE ALL "N" TO AC-FLAGS
           EVALUATE AC-OP
               WHEN "C" PERFORM DO-SIZE-ERROR
               WHEN "N" PERFORM DO-NO-SIZE-ERROR
               WHEN "A" PERFORM DO-A
               WHEN "Z" PERFORM DO-Z
               WHEN "E" PERFORM DO-E
               WHEN "U" PERFORM DO-U
               WHEN "G" PERFORM DO-G
               WHEN "L" PERFORM DO-L
               WHEN "T" PERFORM DO-T
               WHEN "P" PERFORM DO-P
               WHEN OTHER MOVE 99 TO RETURN-CODE
           END-EVALUATE
           GOBACK.

       DO-NO-SIZE-ERROR.
           COMPUTE T-ZONED = AC-SOURCE
           COMPUTE T-UZONED = AC-SOURCE
           COMPUTE T-PACKED = AC-SOURCE
           COMPUTE T-UPACKED = AC-SOURCE
           COMPUTE T-COMP = AC-SOURCE
           COMPUTE T-COMP5 = AC-SOURCE
           COMPUTE T-SCOMP5 = AC-SOURCE
           COMPUTE T-LONG = AC-SOURCE
           COMPUTE T-SEP = AC-SOURCE
           .

       DO-SIZE-ERROR.
           COMPUTE T-ZONED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .

       DO-A.
           COMPUTE T-ZONED ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5 ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5 ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP ROUNDED MODE IS NEAREST-AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .

       DO-Z.
           COMPUTE T-ZONED ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5 ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5 ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP ROUNDED MODE IS NEAREST-TOWARD-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .

       DO-E.
           COMPUTE T-ZONED ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5 ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5 ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP ROUNDED MODE IS NEAREST-EVEN
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .

       DO-U.
           COMPUTE T-ZONED ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5 ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5 ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP ROUNDED MODE IS AWAY-FROM-ZERO
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .

       DO-G.
           COMPUTE T-ZONED ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5 ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5 ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP ROUNDED MODE IS TOWARD-GREATER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .

       DO-L.
           COMPUTE T-ZONED ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5 ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5 ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP ROUNDED MODE IS TOWARD-LESSER
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .

       DO-T.
           COMPUTE T-ZONED ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5 ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5 ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP ROUNDED MODE IS TRUNCATION
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .

       DO-P.
           COMPUTE T-ZONED ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(1:1)
           END-COMPUTE
           COMPUTE T-UZONED ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(2:1)
           END-COMPUTE
           COMPUTE T-PACKED ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(3:1)
           END-COMPUTE
           COMPUTE T-UPACKED ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(4:1)
           END-COMPUTE
           COMPUTE T-COMP ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(5:1)
           END-COMPUTE
           COMPUTE T-COMP5 ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(6:1)
           END-COMPUTE
           COMPUTE T-SCOMP5 ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(7:1)
           END-COMPUTE
           COMPUTE T-LONG ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(8:1)
           END-COMPUTE
           COMPUTE T-SEP ROUNDED MODE IS PROHIBITED
               = AC-SOURCE
               ON SIZE ERROR MOVE "Y" TO AC-FLAGS(9:1)
           END-COMPUTE
           .
