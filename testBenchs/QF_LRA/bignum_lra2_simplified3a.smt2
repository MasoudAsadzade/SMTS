(set-logic QF_LRA)
(declare-fun v3 () Real)
(assert (= v3 (* (/ 1 120030) v3)))
(check-sat)
(exit)
