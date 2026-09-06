;;; Investment Knowledge Base for Joshua
;;; for use with Rule-Based Systems Exercises
;;; 6.871 Spring 2004

(in-package :ju)

; (ask [category-of-fund matt money-market] #'print-answer-with-certainty)



(defun print-answer-with-certainty (backward-support &optional (stream *standard-output*))
  (check-type backward-support cons "backward-support from a query")
  (let ((predication (ask-database-predication backward-support)))
    (check-type predication predication "a predication from a query")
    (terpri stream)
    (ji::truth-value-case  (predication-truth-value predication)
      (*true*
       (prin1 predication stream))
      (*false*
       (write-string "[not " stream)
       (ji::print-without-truth-value predication stream)
       (write-string "]" stream)))
    (format stream " ~d" (certainty-factor predication))))



(defgeneric possesive-suffix (predication))
(defgeneric first-prompt (predication))
(defgeneric second-prompt (predication))
(defgeneric third-prompt (predication))
(defgeneric possible-values (predication))
(defgeneric get-an-answer (predication &optional stream))
(defgeneric appropriate-ptype (predication))
(defgeneric accept-prompt (predication))
(defgeneric question-prefix (predication))
(defgeneric remaining-object-string (predication))

;;; The base mixin
(define-predicate-model question-if-unknown-model () () )

(clim:define-gesture-name :my-rule :keyboard (:r :control :shift))
(clim:define-gesture-name :my-help :keyboard (:h :control :shift))
(clim:define-gesture-name :my-why :keyboard (:w :control :shift))

(defparameter *mycin-help-string*
  "
 ctrl-?  - to show the valid answers to this question
 meta-r  - to show the current rule
 meta-y  - to see why this question is asked
 meta-h  - to see this list"
  )

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;
;;; explaining why we're asking what we're asking
;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(defun print-why (trigger rule &optional (stream *standard-output*))
  (format stream "~%We are trying to determine ") 
  (if (predicationp trigger) 
    (progn (format stream "~a " (question-prefix trigger)) (say trigger stream))
    (princ trigger stream))
  (if (null rule)
    (format stream "~%This is a top level query")
    (let* ((debug-info (ji::rule-debug-info rule))
           (sub-goals (let ((ji::*known-lvs* nil))(eval (ji::rule-debug-info-context debug-info)))))
      (format stream "~%This is being asked for by the rule ~a in order to determine:~%" 
              rule)      
      (format stream "~a " (question-prefix ji::*goal*)) (say ji::*goal* stream)
      (typecase sub-goals
        (ji::and-internal
         (let ((remaining-preds (rest (predication-statement sub-goals)))
               (good-answers nil)
               (remaining-stuff nil)
               (first-remaining-object-string nil))
           (labels ((do-good-preds ()
                      (when remaining-preds
                        (let ((first (pop remaining-preds)))
                          (cond
                           ((not (predicationp first))
                            (push (copy-object-if-necessary first) good-answers)
                            (do-good-preds))
                           (t
                            (let ((found-it nil))
                              (ask first
                                   #'(lambda (just)
                                       (push (ask-database-predication just) good-answers)
                                       (setq found-it t)
                                       (do-good-preds))
                                   :do-backward-rules nil
                                   :do-questions nil)
                              (unless found-it
                                (with-statement-destructured (who value) first
                                  (declare (ignore who))
                                  (with-unification
                                    (unify trigger first)
                                    (setq first-remaining-object-string (remaining-object-string first))
                                    (unify value first-remaining-object-string)
                                    (setq remaining-stuff
                                          (loop for pred in remaining-preds
                                                if (predicationp pred)
                                                collect (with-statement-destructured (who value) pred
                                                          (declare (ignore who))
                                                          (unify value (if (joshua:unbound-logic-variable-p value)
                                                                         (remaining-object-string pred)
                                                                         (joshua:joshua-logic-variable-value value)))
                                                          (copy-object-if-necessary pred))
                                                else collect (copy-object-if-necessary pred)))))))))))))
             (do-good-preds))
           (loop for pred in (nreverse good-answers)
                 for first-time = t then nil
                 if first-time
                 do (format stream "~%It has already been determined whether: ")
                 else do (format stream "~%and whether: ")
                 do (say pred stream))
           (format stream "~%It remains to determine ~a ~a ~a" 
                   (question-prefix trigger) first-remaining-object-string (remaining-stuff-suffix trigger))
           (loop for pred in remaining-stuff
                 do (format stream "~%and ~a ~a ~a" (question-prefix pred) (remaining-object-string pred) (remaining-stuff-suffix pred)))))
        (otherwise ))
      )))

(defmethod remaining-stuff-suffix ((pred predication)) "is")
(defmethod remaining-stuff-suffix ((expression cons)) "")
(defmethod predication-value-description ((pred predication)) (remaining-object-string pred))


;;;;;;;;;;;;;;;;;;;;;;;;;
;;;
;;;  PROTOCOL HACKING
;;;;;;;;;;;;;;;;;;;;;;;;;

(defmethod say ((expression cons) &optional (stream *standard-output*))
  (princ expression stream))

(defmethod remaining-object-string ((expression cons)) (format nil "~a" expression))

(defmethod question-prefix ((expression cons)) "whether")

(defmethod get-an-answer ((predication question-if-unknown-model) &optional (stream *standard-output*))
  "Print the prompt for this parameter (or make one up) and read the reply."
  (fresh-line)
  (flet ((mycin-help (stream action string-so-far)
           (declare (ignore string-so-far))
           (when (member action '(:help :my-help :my-rule :my-why))
             (fresh-line stream)
             (case action
               (:my-why
                (print-why predication ji::*running-rule* stream)
                )
               (:my-rule
                (format stream "You are running the rule ~a" ji::*running-rule*))
               (:my-help
                (format stream *mycin-help-string*)
                ))
             (fresh-line stream)
             (write-string "You are being asked to enter " stream)
             (clim:describe-presentation-type (appropriate-ptype predication) stream)
             (write-char #\. stream)
             )))
    (let ((clim:*help-gestures* (list* :my-help :my-why :my-rule clim:*help-gestures*)))
      (clim:with-accept-help ((:top-level-help #'mycin-help))
        (clim:accept (appropriate-ptype predication)
                     :stream stream
                     :prompt (accept-prompt predication))))))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;  Our pseudo mycin contains 3 types of predications
;;;;  boolean valued, numeric valued, and those that take one of
;;;;  a set of values
;;;;  For each type we provide say methods
;;;;   and a bunch of subordinate methods to make dialog almost English
;;;;   and to do CLIM accepts correctly
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;;;; boolean values
(define-predicate-model value-is-boolean-mixin () () )

(define-predicate-method (say value-is-boolean-mixin) (&optional (stream *standard-output*))
  (with-statement-destructured (who yesno) self
    (format stream "~A~A ~A ~A" 
            who (possesive-suffix self)
            (if (joshua:joshua-logic-variable-value yesno) (first-prompt self) (second-prompt self))
            (third-prompt self))))

(defmethod remaining-object-string ((predication value-is-boolean-mixin))
  (with-statement-destructured (who value) predication
    (declare (ignore value))
    (format nil "~A ~A ~a" 
            (joshua:joshua-logic-variable-value who)
            (first-prompt predication) (third-prompt predication))))

(defmethod appropriate-ptype ((predication value-is-boolean-mixin)) '(clim:member yes no))

(defmethod accept-prompt ((predication value-is-boolean-mixin))
  (with-statement-destructured (who value) predication
    (declare (ignore value))
    (format nil "~%Is it the case that ~a~a ~a ~a" 
            who (possesive-suffix predication)
            (first-prompt predication)
            (third-prompt predication))))

(defmethod question-prefix ((predication value-is-boolean-mixin)) "whether")

(defmethod possible-values ((predication value-is-boolean-mixin)) '("yes" "no"))

(defmethod remaining-stuff-suffix ((pred value-is-boolean-mixin)) "")
(defmethod predication-value-description ((pred value-is-boolean-mixin)) "foobar")


;;;; numeric values

(define-predicate-model value-is-numeric-mixin () () )
(define-predicate-method (say value-is-numeric-mixin) (&optional (stream *standard-output*))
  (with-statement-destructured (who number) self
    (if (joshua:unbound-logic-variable-p number)
      (format stream "is ~a~a ~a"
              who (possesive-suffix self) (first-prompt self))
      (format stream "~A~A ~A is ~A ~A"
              who (possesive-suffix self) 
              (first-prompt self)
              (joshua:joshua-logic-variable-value number)
              (second-prompt self)))))

(defmethod remaining-object-string ((predication value-is-numeric-mixin))
  (with-statement-destructured (who value) predication
    (declare (ignore value))
    (format nil "~A~A ~A" 
            (joshua:joshua-logic-variable-value who) (possesive-suffix predication)
            (first-prompt predication))))

  
(defmethod appropriate-ptype ((predication value-is-numeric-mixin)) 'number)

(defmethod accept-prompt ((predication value-is-numeric-mixin))
  (with-statement-destructured (who value) predication
    (declare (ignore value))
    (format nil "~%What is ~a~a ~a"
            who (possesive-suffix predication) (first-prompt predication))))

(defmethod question-prefix ((predication value-is-numeric-mixin)) "what")

	       
;;; variety of possible values 

(define-predicate-model value-is-option-mixin ()  () )

(define-predicate-method (say value-is-option-mixin) (&optional (stream *standard-output*))
  (with-statement-destructured (who option) self
    (format stream "~A~A ~A ~A ~A"
            who (possesive-suffix self) 
            (first-prompt self)
            (second-prompt self) 
            (joshua:joshua-logic-variable-value option))))

(defmethod remaining-object-string ((predication value-is-option-mixin))
  (with-statement-destructured (who value) predication
    (declare (ignore value))
    (format nil "~A~A ~A" 
            (joshua:joshua-logic-variable-value who) (possesive-suffix predication)
            (first-prompt predication))))

(defmethod appropriate-ptype ((predication value-is-option-mixin)) `(member ,@(possible-values predication)))

(defmethod accept-prompt ((predication value-is-option-mixin))
  (with-statement-destructured (who value) predication
    (declare (ignore value))
    (format nil "~%What is ~a~a ~a" 
            who (possesive-suffix predication) (first-prompt predication))))

(defmethod question-prefix ((predication value-is-option-mixin)) "whether")


;;; Predicate defining macro

(defmacro define-predicate-with-ancillary-info ((pred-name mixin) 
                                                &key 
                                                possesive-suffix 
                                                prompt1 prompt2 prompt3
                                                possible-values
                                                missing-value-prompt
                                                )
  `(eval-when (:compile-toplevel :execute :load-toplevel)
     (define-predicate ,pred-name (who value) (,mixin question-if-unknown-model cf-mixin ltms:ltms-predicate-model))
     (defmethod possesive-suffix ((predication ,pred-name)) () ,possesive-suffix)
     (defmethod first-prompt ((predication ,pred-name)) () ',prompt1)
     (defmethod second-prompt ((predication ,pred-name)) () ',prompt2)
     ,(when prompt3 `(defmethod third-prompt ((predication ,pred-name)) () ',prompt3))
     ,(when possible-values `(defmethod possible-values ((predication ,pred-name)) ',possible-values))
     ,(when missing-value-prompt `(defmethod missing-value-prompt ((predication ,pred-name)) ',missing-value-prompt))
  ))

;;; predicates that take numeric values
(define-predicate-with-ancillary-info (age value-is-numeric-mixin)
  :possesive-suffix "'s" :prompt1 "age" :prompt2 "years old")
(define-predicate-with-ancillary-info (age-of-oldest-child value-is-numeric-mixin)
  :possesive-suffix "'s" :prompt1 "oldest child's age" :prompt2 "years old")
(define-predicate-with-ancillary-info (age-of-youngest-child value-is-numeric-mixin)
  :possesive-suffix "'s" :prompt1 "youngest child's age" :prompt2 "years old")
(define-predicate-with-ancillary-info (current-savings value-is-numeric-mixin)
  :possesive-suffix "'s" :prompt1 "current savings" :prompt2 "dollars")
(define-predicate-with-ancillary-info (monthly-salary value-is-numeric-mixin)
  :possesive-suffix "'s" :prompt1 "monthly salary" :prompt2 "dollars")
(define-predicate-with-ancillary-info (years-until-retirement value-is-numeric-mixin)
  :possesive-suffix "'s" :prompt1 "time left before retirement" :prompt2 "years")

;;; Predicates that take one of a set of values
(define-predicate-with-ancillary-info (tax-bracket value-is-option-mixin)
  :possesive-suffix "'s" :prompt1 "tax bracket" :prompt2 "is"
  :possible-values (high medium low))
(define-predicate-with-ancillary-info (category-of-fund value-is-option-mixin)
  :possesive-suffix "'s" :prompt1 "recommended category of fund" :prompt2 "is"
  :possible-values (MONEY-MARKET CONSERVATIVE-GROWTH GROWTH-AND-INCOME AGGRESSIVE INCOME TAX-FREE))
(define-predicate-with-ancillary-info (risk-tolerance-level value-is-option-mixin)
  :possesive-suffix "'s" :prompt1 "risk tolerance" :prompt2 "is" 
  :possible-values (high medium low))
(define-predicate-with-ancillary-info (childs-college-tuition value-is-option-mixin)
  :possesive-suffix "'s" :prompt1 "child's college tuition" :prompt2 "is likely to be"
  :possible-values (EXPENSIVE CHEAP))
(define-predicate-with-ancillary-info (investment-goal value-is-option-mixin)
  :possesive-suffix "'s" :prompt1 "investment goal" :prompt2 "is"
  :possible-values (RETIREMENT CHILDRENS-EDUCATION CURRENT-INCOME HOME-OWNERSHIP INVEST-SPARE-CASH))
(define-predicate-with-ancillary-info (life-stage value-is-option-mixin)
  :possesive-suffix "'s" :prompt1 "stage of life" :prompt2 "is" 
  :possible-values (retired not-retired))
(define-predicate-with-ancillary-info (adequacy-of-insurance-coverage value-is-option-mixin)
  :possesive-suffix "'s" :prompt1 "insurance coverage" :prompt2 "is" 
  :possible-values (adequate inadequate))

;;; boolean valued predicates
(define-predicate-with-ancillary-info (budget-but-splurge-sometimes value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "budgets" :prompt2 "doesn't budget" :prompt3 "but splurges sometimes")
(define-predicate-with-ancillary-info (budgeting-is-important value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "thinks" :prompt2 "doesn't think" :prompt3 "budgeting is important")
(define-predicate-with-ancillary-info (child-is-eligible-for-loans value-is-boolean-mixin)
  :possesive-suffix "'s child" :prompt1 "is eligible" :prompt2 "is ineligible" :prompt3 "for educational loans")
(define-predicate-with-ancillary-info (child-has-scholarship value-is-boolean-mixin)
  :possesive-suffix "'s child" :prompt1 "has" :prompt2 "doesn't have" :prompt3 "a scholarship")
(define-predicate-with-ancillary-info (child-has-trust-fund value-is-boolean-mixin)
  :possesive-suffix "'s child" :prompt1 "has" :prompt2 "doesn't have" :prompt3 "a trust fund")
(define-predicate-with-ancillary-info (child-headed-for-college value-is-boolean-mixin)
  :possesive-suffix "'s child" :prompt1 "is" :prompt2 "isn't" :prompt3 "headed for college")
(define-predicate-with-ancillary-info (childs-education-already-funded value-is-boolean-mixin)
  :possesive-suffix "'s child's education" :prompt1 "is" :prompt2 "isn't" :prompt3 "already funded")
(define-predicate-with-ancillary-info (enjoys-gambling value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "enjoys" :prompt2 "doesn't enjoy" :prompt3 "gambling")
(define-predicate-with-ancillary-info (has-children value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "has" :prompt2 "doesn't have" :prompt3 "children")
(define-predicate-with-ancillary-info (has-health-insurance value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "has" :prompt2 "doesn't have" :prompt3 "health insurance")
(define-predicate-with-ancillary-info (has-life-insurance value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "has" :prompt2 "doesn't have" :prompt3 "life insurance")
(define-predicate-with-ancillary-info (has-ira value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "has" :prompt2 "doesn't have" :prompt3 "an IRA")
(define-predicate-with-ancillary-info (has-pension value-is-boolean-mixin)
    :possesive-suffix "" :prompt1 "has" :prompt2 "doesn't have" :prompt3 "a pension")
(define-predicate-with-ancillary-info (has-retirement-vehicle value-is-boolean-mixin)
    :possesive-suffix "" :prompt1 "has" :prompt2 "doesn't have" :prompt3 "a retirement vehicle")
(define-predicate-with-ancillary-info (is-married value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "is" :prompt2 "isn't" :prompt3 "married")
(define-predicate-with-ancillary-info (owns-home value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "owns" :prompt2 "doesn't own" :prompt3 "a home")
(define-predicate-with-ancillary-info (should-have-life-insurance value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "should have" :prompt2 "shouldn't have" :prompt3 "life insurance")
(define-predicate-with-ancillary-info (wants-home value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "wants" :prompt2 "doesn't want" :prompt3 "to own a home")
(define-predicate-with-ancillary-info (worries-about-money-at-night value-is-boolean-mixin)
  :possesive-suffix "" :prompt1 "worries" :prompt2 "doesn't worry" :prompt3 "about money at night")

;; using this model, the system will ask the user any time 
;; it needs a specific fact to continue backward chaining.

;;; we should only be asking a question under the following
;;; circumstances:
;;; 
;;; the predication being asked contains no logic variables
;;; eg. [has-health-insurance matt yes], not
;;; [has-health-insurance matt ?x]
;;;
;;; AND
;;;
;;; that predication is not already in the database
;;;
;;; AND
;;;
;;; any other predication matching the predicate and ?who
;;; eg. [has-health-insurance matt no] is not already in the
;;; database.
;;;
;;; AND
;;;
;;; there is no rule we can use to find out the answer
;;; 
;;; this can be told by check [known [has-health-insurance matt ?]]


(define-predicate already-known (predicate object))

;;; if after doing the normal processing nothing is found
;;; then finally ask the guy a question if appropriate
(define-predicate-method (ask question-if-unknown-model) (intended-truth-value continuation do-backward-rules do-questions)
  (let ((answers nil)
        (predicate (predication-predicate self)))
    (flet ((my-continuation (bs)
             (let* ((answer (ask-query bs))
                    (database-answer (insert (copy-object-if-necessary answer))))
               (pushnew database-answer answers))))
      (with-statement-destructured (who value) self
        (declare (ignore value))
        (with-unbound-logic-variables (value)
          (let ((predication `[,predicate ,who ,value]))
            ;; first see if there's an answer already in the database
            ;; may want to change this to asserting already-know predication, but I'm trying to avoid that
            (ask-data predication intended-truth-value #'my-continuation)
            (unless answers
              ;; Now go get stuff from rules.
              (when do-backward-rules
                (ask-rules predication intended-truth-value #'my-continuation do-questions))
              ;; now go hack questions
              (unless answers
                (when do-questions
                  (ask-questions predication intended-truth-value #'my-continuation))))))
        ;; if he's doing a raws database fetch, don't ask
        (when (and (null answers) (or do-backward-rules do-questions))
          (unless (joshua:unbound-logic-variable-p who)
            (let* ((answer (get-an-answer self))
    	           (database-answer (tell `[,predicate ,who ,answer]
		                          :justification '((user-input 1.0)))))
              (pushnew database-answer answers))))))
    (loop for answer in answers
          when (eql (predication-truth-value answer) intended-truth-value)
          do (with-stack-list (just self intended-truth-value answer)
               (with-unification 
                 (unify self answer)
                 (funcall continuation just)))))
  ;; make it clear that there is no interesting return value
  (values))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;                                                             ;;;
;;; Inference Rules (For importance, higher values go first.)   ;;;
;;; RULES ABOUT: adequacy of Basic Insurance Coverage           ;;;
;;;                                                             ;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(defrule health-insurance-coverage (:backward :certainty 1.0 :importance 99)
  if [has-health-insurance ?who no]
  then [adequacy-of-insurance-coverage ?who inadequate])

(defrule life-insurance-coverage (:backward :certainty 1.0 :importance 98)
  if [and [has-life-insurance ?who no]
          [should-have-life-insurance ?who yes]]
  then [adequacy-of-insurance-coverage ?who inadequate])

(defrule full-insurance-coverage (:backward :certainty 1.0 :importance 97)
  if [and [has-life-insurance ?who yes]
          [has-health-insurance ?who yes]]
  then [adequacy-of-insurance-coverage ?who adequate])

;;; RULES ABOUT: whether you Should Have Life Insurance
(defrule need-for-life-insurance (:backward :certainty 1.0 :importance 96)
  if [or [is-married ?who yes]
         [has-children ?who yes]]
  then [should-have-life-insurance ?who yes])

;; ;;; RULES ABOUT: which Category Of Fund to choose
(defrule insurance-coverage-adequacy (:backward :certainty 1.0 :importance 90)
  if [adequacy-of-insurance-coverage ?who inadequate]
  then [category-of-fund ?who none])

(defrule money-market (:backward :certainty 1.0 :importance 89)
  if [and [current-savings ?who ?x]
          [monthly-salary ?who ?y]
          (< ?x (* 6 ?y))]
  then [category-of-fund ?who money-market])

(defrule short-term-retirement (:backward :certainty 0.8 :importance 88)
  if [and [investment-goal ?who retirement]
          [years-until-retirement ?who ?x]
          (< ?x 10)]
  then [category-of-fund ?who conservative-growth])

(defrule moderate-term-retirement (:backward :certainty 0.8 :importance 87)
 if [and [investment-goal ?who retirement]
          [years-until-retirement ?who ?x]
	  (and (> ?x 10) (< ?x 20))]
  then [category-of-fund ?who growth-and-income])

(defrule long-term-retirement (:backward :certainty 0.8 :importance 86)
 if [and [investment-goal ?who retirement]
         [years-until-retirement ?who ?x]
         (> ?x 20)]
  then [category-of-fund ?who aggressive])

(defrule long-term-education (:backward :certainty 0.8 :importance 85)
  if [and [has-children ?who yes]
          [investment-goal ?who childrens-education]
          [age-of-oldest-child ?who ?x]
          (< ?x 7)]
  then [category-of-fund ?who growth-and-income])

(defrule short-term-education (:backward :certainty 0.8 :importance 84)
  if [and [has-children ?who yes]
          [investment-goal ?who childrens-education]
          [age-of-oldest-child ?who ?x]
          (> ?x 7)]
  then [category-of-fund ?who conservative-growth])

(defrule home-ownership (:backward :certainty 0.9 :importance 83)
  if [investment-goal ?who home-ownership]
  then [category-of-fund ?who growth-and-income])

(defrule current-income (:backward :certainty 0.9 :importance 82)
  if [investment-goal ?who current-income]
  then [category-of-fund ?who income])

(defrule invest-spare-cash-low (:backward :certainty 0.9 :importance 81)
  if [and [investment-goal ?who invest-spare-cash]
          [risk-tolerance-level ?who low]]
  then [category-of-fund ?who conservative-growth])

(defrule invest-spare-cash-medium (:backward :certainty 0.8 :importance 80)
  if [and [investment-goal ?who invest-spare-cash]
          [risk-tolerance-level ?who medium]]
  then [category-of-fund ?who growth-and-income])

(defrule invest-spare-cash-high (:backward :certainty 0.8 :importance 79)
  if [and [investment-goal ?who invest-spare-cash]
          [risk-tolerance-level ?who high]]
  then [category-of-fund ?who aggressive])

(defrule invest-spare-cash-taxfree (:backward :certainty 0.9 :importance 78)
  if [and [investment-goal ?who invest-spare-cash]
          [risk-tolerance-level ?who medium]
	  [tax-bracket ?who high]]
  then [category-of-fund ?who tax-free])

;;; RULES ABOUT: what your Life Stage is
(defrule life-stage-retired (:backward :certainty 0.8 :importance 77)
  if [and [age ?who ?x]
          (> ?x 65)]
  then [life-stage ?who retired])

(defrule life-stage-not-retired (:backward :certainty 0.8 :importance 76)
  if [and [age ?who ?x]
          (<= ?x 65)]
  then [life-stage ?who not-retired])
  
;;; RULES ABOUT: what Investment Goal to select
(defrule goal-retirement (:backward :certainty 1.0 :importance 69)
  if [and [has-pension ?who no]
          [has-ira ?who no]]
  then [investment-goal ?who retirement])

(defrule goal-childrens-education (:backward :certainty 0.8 :importance 68)
  if [and [has-children ?who yes]
          [child-headed-for-college ?who yes]
          [childs-education-already-funded ?who no]]
  then [investment-goal ?who childrens-education])

(defrule goal-home-ownership (:backward :certainty 0.8 :importance 67)
  if [and [owns-home ?who no]
          [wants-home ?who yes]]
  then [investment-goal ?who home-ownership])

(defrule goal-current-income (:backward :certainty 0.9 :importance 66)
  if [life-stage ?who retired]
  then [investment-goal ?who current-income])

(defrule retirement-vehicle-1 (:forward :certainty 1.0)
  if [has-pension ?who yes]
  then [has-retirement-vehicle ?who yes])

(defrule retirement-vehicle-2 (:forward :certainty 1.0)
  if [has-ira ?who yes]
  then [has-retirement-vehicle ?who yes])

(defrule goal-invest-spare-cash (:backward :certainty 0.8 :importance 65)
  if [and [or [owns-home ?who yes]
              [and [owns-home ?who no]
                   [wants-home ?who no]]]
          [has-retirement-vehicle ?who yes]
          [or [has-children ?who no]
              [and [has-children ?who yes]
                   [childs-education-already-funded ?who yes]]]
	  [life-stage ?who not-retired]]
  then [investment-goal ?who invest-spare-cash])

;;; RULES ABOUT: what your Risk Tolerance is
(defrule high-risk-tolerance (:backward :certainty 0.8 :importance 59)
  if [enjoys-gambling ?who yes]
  then [risk-tolerance-level ?who high])

(defrule low-risk-tolerance (:backward :certainty 0.8 :importance 58)
  if [budgeting-is-important ?who yes]
  then [risk-tolerance-level ?who low])

(defrule low-risk-tolerance-2 (:backward :certainty 0.8 :importance 57)
  if [worries-about-money-at-night ?who yes]
  then [risk-tolerance-level ?who low])

(defrule medium-risk-tolerance (:backward :certainty 0.8 :importance 56)
  if [budget-but-splurge-sometimes ?who yes]
  then [risk-tolerance-level ?who medium])

;;; RULES ABOUT: whether you have Children Headed for College

(defrule college-bound-children (:backward :certainty 1.0 :importance 55)
  if [and [has-children ?who yes]
          [age-of-youngest-child ?who ?x]
          (< ?x 16)]
  then [child-headed-for-college ?who yes])

(defrule no-college-bound-children (:backward :certainty 1.0 :importance 54)
  if [and [has-children ?who yes]
          [age-of-youngest-child ?who ?x]
          (>= ?x 16)
          ]
  then [child-headed-for-college ?who no])

(defrule no-children (:backward :certainty 1.0 :importance 53)
  if [has-children ?who no]
  then [child-headed-for-college ?who no])

;;; RULES ABOUT: whether Children's Education Already Funded
(defrule cheap-school (:backward :certainty 1.0 :importance 49)
  if [and [has-children ?who yes]
          [childs-college-tuition ?who cheap]]
  then [childs-education-already-funded ?who yes])

(defrule scholarship (:backward :certainty 1.0 :importance 48)
  if [and [has-children ?who yes] [child-has-scholarship ?who yes]]
  then [childs-education-already-funded ?who yes])

(defrule eligible-for-loans (:backward :certainty 1.0 :importance 47)
  if [and [has-children ?who yes] [child-is-eligible-for-loans ?who yes]]
  then [childs-education-already-funded ?who yes])

(defrule trust-fund (:backward :certainty 1.0 :importance 46)
  if [and [has-children ?who yes] [child-has-trust-fund ?who yes]]
  then [childs-education-already-funded ?who yes])

(defrule education-not-funded (:backward :certainty 1.0 :importance 45)
  if [or [and [has-children ?who yes] [child-has-scholarship ?who no]]
         [and [has-children ?who yes] [child-is-eligible-for-loans ?who no]]
	 [and [has-children ?who yes] [child-has-trust-fund ?who no]]]
  then [childs-education-already-funded ?who no])

(defun rules-concluding-predicate (pred)
  (let ((answers nil))
    (map-over-backward-rule-triggers `[,pred ? ?]
                                     #'(lambda (trigger) (pushnew (ji::backward-trigger-rule trigger) answers)))
    answers))

(defun predicates-rule-relies-on (rule)
  (let ((answers nil))
    (labels ((do-one-level (stuff)
                 (let ((connective (when (predication-maker-p stuff) (predication-maker-predicate stuff))))
                   (case connective
                     ((and or)
                      (with-predication-maker-destructured (&rest more-stuff) stuff
                        (loop for thing in more-stuff
                              do (do-one-level thing))))
                     ((nil))
                     (otherwise
                      (pushnew connective answers))
                     ))))
        (do-one-level (ji::rule-debug-info-context (ji::rule-debug-info rule))))
    answers))
      

(defun graph-rule-tree (predicates &key (orientation :vertical) (size :small) (stream *standard-output*))
  (terpri stream)
  (clim:with-text-size (stream size)
    (clim:format-graph-from-roots
     (loop for pred in predicates
           collect (list 'predicate pred))
     #'(lambda (thing stream)
         (destructuring-bind (type name) thing
           (case type
             (predicate
              (clim:surrounding-output-with-border (stream)
                (princ name stream)))
             (rule
              (clim:surrounding-output-with-border (stream :shape :oval)
                (princ name stream))))))
     #'(lambda (thing)
         (destructuring-bind (type name) thing
           (case type
             (predicate (loop for r in (rules-concluding-predicate name)
                              collect (list 'rule r)))
             (rule (loop for p in (predicates-rule-relies-on name)
                         collect (list 'predicate p))))))
     :stream stream
     :orientation orientation
     :merge-duplicates t
     :duplicate-test #'equal)))

(clim-env::define-lisp-listener-command (com-graph-rules :name t)
                                        ((predicates `(clim:sequence (member ,@(loop for pred being the hash-keys of ji::*all-predicates* collect pred)))
                                                     :prompt "A sequence of predicates")
                                         &key
                                         (orientation `(clim:member :vertical :horizontal) :default :vertical)
                                         (size `(clim:member :tiny :very-small :small :normal :large :very-large :huge)
                                               :default :small)
                                         (to-file 'clim:pathname :default nil)
                                         (page-orientation '(clim:member :portrait :landscape) 
                                                           :default :portrait
                                                           :prompt "If to file, print in portrait or landscape format")
                                         (multi-page 'clim:boolean :default nil :prompt "If to file, segment into multiple pages")
                                         (scale-to-fit 'clim:boolean :default nil :prompt "If to file, scale to fit one page"))
   (if to-file
     (with-open-file (file to-file :direction :output :if-exists :supersede :if-does-not-exist :create)
       (clim:with-output-to-postscript-stream (stream file 
                                                      :multi-page multi-page 
                                                      :scale-to-fit scale-to-fit  
                                                      :orientation page-orientation)
         (graph-rule-tree predicates :orientation orientation :size size :stream stream)))
     (graph-rule-tree predicates :orientation orientation :size size)))
                                        
