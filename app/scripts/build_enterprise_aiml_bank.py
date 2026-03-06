import json
from pathlib import Path

from app.services.question_bank.validator import validate_question_bank

DATA_DIR = Path("app/services/question_bank/data")
BANK_KEY = "AI/ML/ai_ml_engineering.json"
DEFAULT_VERSIONS = ["python311", "sklearn", "pytorch", "mlflow"]
SECTIONS = [
    {
        "topic": "Data Splitting, Leakage, and Experiment Design",
        "versions": ["python311", "sklearn", "mlflow"],
        "items": [
            {
                "difficulty": "easy",
                "style": "debugging",
                "question": "A churn model is trained on session rows and split randomly, so the same user appears in both train and validation. Validation AUC looks suspiciously high. What is the main flaw?",
                "options": [
                    "The split leaks user-specific patterns across both sets and should be replaced with a user-level or GroupKFold split.",
                    "Random splits are always preferred because they reduce variance more than grouped splits.",
                    "The model should switch to k-means because churn labels are unstable under random shuffling.",
                    "The AUC is high only because the dataset has too many engineered features.",
                ],
                "correct_answer": "The split leaks user-specific patterns across both sets and should be replaced with a user-level or GroupKFold split.",
                "tags": ["leakage", "group-cv", "churn"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A time-series demand model standardizes every feature before the train-test split. Why is that unsafe?",
                "options": [
                    "The scaler is using future distribution statistics and leaking information from the test window into training.",
                    "Standardization cannot be used on time-series features under any deployment pattern.",
                    "The scaler will force the target variable to become normally distributed before fitting.",
                    "Time-series data should always be normalized with MinMaxScaler instead of StandardScaler.",
                ],
                "correct_answer": "The scaler is using future distribution statistics and leaking information from the test window into training.",
                "tags": ["time-series", "scaling", "leakage"],
            },
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "A fraud model is tuned with repeated reference to the final holdout results while features are still being engineered. What principle is being violated?",
                "options": [
                    "The holdout is no longer an unbiased final estimate because it is being used for iterative model decisions.",
                    "A holdout set should be shuffled every hour so feature engineering stays representative.",
                    "Holdout data should contain only minority-class examples to maximize fraud recall.",
                    "A single holdout can be reused indefinitely if the model family does not change.",
                ],
                "correct_answer": "The holdout is no longer an unbiased final estimate because it is being used for iterative model decisions.",
                "tags": ["holdout", "experiment-design", "model-selection"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A feature pipeline computes a seven-day rolling average but the SQL window accidentally includes the current label day. Offline metrics jump, then production performance collapses. What happened?",
                "options": [
                    "The rolling feature leaks target-era information into training and must be rebuilt with a strictly historical window.",
                    "The rolling feature is too smooth and should be replaced with a one-day lag to avoid underfitting.",
                    "The SQL engine is caching rows, so the feature drift is only an execution-speed problem.",
                    "The jump in offline metrics proves the model is production-ready and the collapse must be monitoring noise.",
                ],
                "correct_answer": "The rolling feature leaks target-era information into training and must be rebuilt with a strictly historical window.",
                "tags": ["rolling-window", "sql", "label-leakage"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A target-encoded feature is computed on the full dataset before cross-validation. Why does the CV score become unreliable?",
                "options": [
                    "Each fold receives statistics influenced by its own labels, so the encoding leaks target information across folds.",
                    "Target encoding always lowers validation scores because it removes minority categories.",
                    "Cross-validation cannot be combined with target encoding under binary classification.",
                    "The encoding fails only because the dataset should use one-hot vectors instead of numeric aggregates.",
                ],
                "correct_answer": "Each fold receives statistics influenced by its own labels, so the encoding leaks target information across folds.",
                "tags": ["target-encoding", "cross-validation", "leakage"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A recommendation team evaluates several prompt and retriever changes on the same 500 labeled examples until one variant wins. What is the main risk?",
                "options": [
                    "They are overfitting decisions to the evaluation set and weakening the credibility of the reported gain.",
                    "A fixed evaluation set is invalid because prompt systems must be scored only with live traffic.",
                    "The same 500 examples should be reused until every variant exceeds the same threshold.",
                    "Repeated evaluation is harmless if the chosen metric is normalized between zero and one.",
                ],
                "correct_answer": "They are overfitting decisions to the evaluation set and weakening the credibility of the reported gain.",
                "tags": ["eval-set", "overfitting", "llm-evaluation"],
            },
            {
                "difficulty": "medium",
                "style": "architecture",
                "question": "A marketplace ranking model is trained on seller-level labels but the data split is done at listing level. What is the strongest redesign?",
                "options": [
                    "Split by seller or another stable entity boundary so related observations do not straddle train and validation.",
                    "Increase the number of folds while keeping the listing-level split so leakage averages out.",
                    "Downsample large sellers so the listing-level split becomes less biased.",
                    "Switch to a simpler model because split strategy matters only for deep learning systems.",
                ],
                "correct_answer": "Split by seller or another stable entity boundary so related observations do not straddle train and validation.",
                "tags": ["group-split", "ranking", "marketplace"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "An experimentation dashboard shows a new uplift model gaining 6 percent offline lift, but the feature notebook reveals that post-campaign engagement signals were joined into training rows. What is the root cause?",
                "options": [
                    "The model learned from signals that were only observable after the treatment window, so the uplift estimate is contaminated by post-outcome leakage.",
                    "Uplift models should never use engagement data because treatment response must be modeled only with demographics.",
                    "The dashboard is wrong because offline lift cannot exceed online lift on any binary outcome task.",
                    "Joining engagement signals after the campaign window only affects latency, not label validity.",
                ],
                "correct_answer": "The model learned from signals that were only observable after the treatment window, so the uplift estimate is contaminated by post-outcome leakage.",
                "tags": ["uplift", "causal-inference", "post-outcome-leakage"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A claims model uses nested CV, but the outer-fold scores still look implausibly strong. Investigation shows that a rare-category bucketing map was fit once before the outer loop. Why is that still a problem?",
                "options": [
                    "The preprocessing step was learned on data outside each outer training fold, so information still leaked into evaluation.",
                    "Nested CV automatically protects every preprocessing decision, even if it is fit globally first.",
                    "Rare-category bucketing cannot affect model validation because it does not use the target variable.",
                    "Outer folds should always reuse the same preprocessing object so metric variance stays low.",
                ],
                "correct_answer": "The preprocessing step was learned on data outside each outer training fold, so information still leaked into evaluation.",
                "tags": ["nested-cv", "preprocessing", "leakage"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "An A/B test for a fraud model is stopped after two days because the treatment shows p=0.03 on approval rate, but chargeback labels arrive weeks later. What is the operational mistake?",
                "options": [
                    "The team optimized on an early proxy without waiting for the business-critical delayed outcome and also peeked before the planned horizon.",
                    "Delayed labels mean the experiment should use no statistics at all and rely on manager judgment instead.",
                    "Approval rate is always a better production target than chargeback rate because it is available sooner.",
                    "The p-value proves the change is safe to ship regardless of the missing delayed labels.",
                ],
                "correct_answer": "The team optimized on an early proxy without waiting for the business-critical delayed outcome and also peeked before the planned horizon.",
                "tags": ["ab-testing", "delayed-labels", "peeking"],
            },
        ],
    },
    {
        "topic": "Feature Engineering and Representation Learning",
        "versions": ["python311", "sklearn", "pytorch", "mlflow"],
        "items": [
            {
                "difficulty": "easy",
                "style": "debugging",
                "question": "A critical numeric feature is missing for 30 percent of rows, and the missingness itself is correlated with the target. Which fix is strongest?",
                "options": [
                    "Add a missingness indicator and impute the value separately so the model can use the pattern without losing rows.",
                    "Drop every row with a missing value because correlation with the target makes imputation invalid.",
                    "Fill missing values with zero and avoid any indicator because the model will infer missingness from the zero.",
                    "Remove the feature entirely because predictive missingness always causes leakage.",
                ],
                "correct_answer": "Add a missingness indicator and impute the value separately so the model can use the pattern without losing rows.",
                "tags": ["missing-data", "indicators", "imputation"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A model one-hot encodes 40,000 ZIP codes and training memory spikes. What alternative is usually more practical?",
                "options": [
                    "Use a reduced-cardinality strategy such as target encoding with leakage controls, hashing, or learned embeddings.",
                    "Keep the one-hot matrix and switch every linear model to k-nearest neighbors.",
                    "Collapse all ZIP codes into one category so the feature no longer consumes memory.",
                    "Standardize the one-hot columns so the matrix becomes dense and easier to train on.",
                ],
                "correct_answer": "Use a reduced-cardinality strategy such as target encoding with leakage controls, hashing, or learned embeddings.",
                "tags": ["categorical-features", "high-cardinality", "memory"],
            },
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "A dense text embedding model is retrained, but the production ANN index is not rebuilt. What failure should engineers expect first?",
                "options": [
                    "Retrieval quality will degrade because the stored vectors and the live query encoder no longer share the same representation space.",
                    "The ANN index will automatically self-heal because cosine similarity is representation agnostic.",
                    "Only ingestion latency will change because embeddings do not affect nearest-neighbor ordering.",
                    "The issue matters only for Euclidean distance, not for cosine or dot-product search.",
                ],
                "correct_answer": "Retrieval quality will degrade because the stored vectors and the live query encoder no longer share the same representation space.",
                "tags": ["embeddings", "ann", "representation-drift"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A support classifier trains on lowercased text with punctuation stripped, but the serving service tokenizes raw mixed-case strings. Accuracy drops after deployment. What is the most likely cause?",
                "options": [
                    "Training-serving skew from inconsistent text preprocessing is shifting the input feature distribution.",
                    "Lowercasing during training causes the model to forget all stop words at serving time.",
                    "Mixed-case text should always improve recall because it preserves more entropy for the model.",
                    "The issue proves the tokenizer library cannot be used with any classification pipeline.",
                ],
                "correct_answer": "Training-serving skew from inconsistent text preprocessing is shifting the input feature distribution.",
                "tags": ["training-serving-skew", "tokenization", "text-preprocessing"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A feature store serves yesterday's customer tenure value online while offline training uses a point-in-time correct snapshot. What kind of issue is this?",
                "options": [
                    "A train-serve consistency problem caused by stale online features that no longer match the offline training semantics.",
                    "A harmless caching optimization because tenure changes slowly for most customers.",
                    "A model calibration problem that should be fixed only with isotonic regression.",
                    "A concurrency issue in the feature store that affects only write throughput and not model quality.",
                ],
                "correct_answer": "A train-serve consistency problem caused by stale online features that no longer match the offline training semantics.",
                "tags": ["feature-store", "staleness", "train-serve-consistency"],
            },
            {
                "difficulty": "medium",
                "style": "concept",
                "question": "A retrieval system combines sparse BM25 scores with dense embedding similarity. Why can that be better than using only one representation?",
                "options": [
                    "Sparse and dense signals capture different evidence, so hybrid retrieval can improve recall across lexical and semantic matches.",
                    "Dense retrieval works only for images, so BM25 is required for all text systems.",
                    "Hybrid scoring removes the need to tune chunking or reranking downstream.",
                    "BM25 and embedding search are mathematically identical after feature scaling.",
                ],
                "correct_answer": "Sparse and dense signals capture different evidence, so hybrid retrieval can improve recall across lexical and semantic matches.",
                "tags": ["retrieval", "hybrid-search", "embeddings"],
            },
            {
                "difficulty": "medium",
                "style": "architecture",
                "question": "A team plans to compute a heavy geospatial feature inside both the training notebook and the online prediction API. What is the main architectural risk?",
                "options": [
                    "Duplicating feature logic invites training-serving skew and inconsistent bug fixes across offline and online paths.",
                    "The main risk is only that geospatial features cannot be cached by modern serving stacks.",
                    "Feature duplication is acceptable because offline and online systems should intentionally diverge.",
                    "The design is safe as long as both code paths use Python and the same cloud account.",
                ],
                "correct_answer": "Duplicating feature logic invites training-serving skew and inconsistent bug fixes across offline and online paths.",
                "tags": ["feature-store", "architecture", "consistency"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "An embeddings pipeline silently switches one numeric feature from milliseconds to seconds for new data only. Offline retraining on historical data still looks fine, but online retrieval quality falls. Why is this failure hard to catch?",
                "options": [
                    "The representation shift appears only in live inputs, so offline replay without the changed transform will miss the production mismatch.",
                    "Unit changes cannot affect embeddings because neural networks rescale all numeric features automatically.",
                    "Retrieval quality should improve because seconds create a more compact numeric range than milliseconds.",
                    "The issue would surface only if the model used tree features rather than embeddings.",
                ],
                "correct_answer": "The representation shift appears only in live inputs, so offline replay without the changed transform will miss the production mismatch.",
                "tags": ["unit-mismatch", "embeddings", "production-debugging"],
            },
            {
                "difficulty": "hard",
                "style": "scenario",
                "question": "A search team must choose between target encoding and learned embeddings for a seller-id feature with 500,000 categories and a nonstationary label distribution. Which tradeoff matters most?",
                "options": [
                    "Both reduce dimensionality, but target encoding is more leakage-prone and brittle under distribution shifts, while embeddings need enough signal and serving support.",
                    "Target encoding is always safer because it never depends on label quality or smoothing choices.",
                    "Learned embeddings remove the need for cold-start handling because new IDs inherit the global vector automatically.",
                    "Neither method can be used once cardinality exceeds ten thousand categories.",
                ],
                "correct_answer": "Both reduce dimensionality, but target encoding is more leakage-prone and brittle under distribution shifts, while embeddings need enough signal and serving support.",
                "tags": ["target-encoding", "embeddings", "high-cardinality"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "A feature join doubles the row count for a minority class because one customer key maps to multiple profile records. Training metrics improve, but deployment fails badly. What is the root issue?",
                "options": [
                    "The pipeline created duplicate training examples through an incorrect join cardinality, distorting the label distribution and feature frequencies.",
                    "The minority class should always be oversampled by duplicating rows directly inside the join.",
                    "Join cardinality problems affect only warehouse cost and not model behavior once regularization is enabled.",
                    "The deployment failure proves the online system needs a larger batch size for feature retrieval.",
                ],
                "correct_answer": "The pipeline created duplicate training examples through an incorrect join cardinality, distorting the label distribution and feature frequencies.",
                "tags": ["feature-joins", "data-quality", "label-distribution"],
            },
        ],
    },
    {
        "topic": "Classical ML Algorithms and Optimization",
        "versions": ["python311", "sklearn", "xgboost", "optuna"],
        "items": [
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "A tabular classifier needs to remove irrelevant features entirely rather than just shrink them. Which regularization family is more aligned with that goal?",
                "options": [
                    "L1 regularization because it can drive some coefficients exactly to zero under the right settings.",
                    "L2 regularization because it always removes more features than L1 in sparse settings.",
                    "Dropout because it permanently deletes coefficients in linear models after training.",
                    "Early stopping because it guarantees a sparse model representation.",
                ],
                "correct_answer": "L1 regularization because it can drive some coefficients exactly to zero under the right settings.",
                "tags": ["regularization", "feature-selection", "linear-models"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A very sparse text dataset with millions of rows and a tight latency budget needs a first strong baseline. Which choice is most pragmatic?",
                "options": [
                    "A linear model over sparse features because it is fast to train, cheap to serve, and often strong on high-dimensional text.",
                    "A deep CNN because every sparse problem should start with a large neural network.",
                    "KNN because sparse vectors make nearest-neighbor search more reliable at scale.",
                    "A GAN because generative training improves every downstream classifier baseline.",
                ],
                "correct_answer": "A linear model over sparse features because it is fast to train, cheap to serve, and often strong on high-dimensional text.",
                "tags": ["baselines", "sparse-text", "latency"],
            },
            {
                "difficulty": "easy",
                "style": "debugging",
                "question": "A KNN classifier performs well on five features but collapses after hundreds of noisy dimensions are added. What is the most likely reason?",
                "options": [
                    "High-dimensional space makes distances less informative, so nearest-neighbor comparisons become unreliable without feature selection or reduction.",
                    "KNN cannot be used once the feature count exceeds the number of classes in the dataset.",
                    "The algorithm needs batch normalization to stabilize the Euclidean distance calculation.",
                    "The collapse proves the labels are shuffled because KNN is immune to irrelevant features.",
                ],
                "correct_answer": "High-dimensional space makes distances less informative, so nearest-neighbor comparisons become unreliable without feature selection or reduction.",
                "tags": ["knn", "curse-of-dimensionality", "feature-selection"],
            },
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "A clustering workflow applies k-means directly to features with very different scales. What failure mode is most likely?",
                "options": [
                    "Large-scale features dominate the distance calculation and bias the cluster assignments.",
                    "K-means automatically normalizes each column, so the scale difference is irrelevant.",
                    "The algorithm becomes density-based once feature magnitudes differ by more than ten times.",
                    "Feature scale matters only for hierarchical clustering and not for centroid methods.",
                ],
                "correct_answer": "Large-scale features dominate the distance calculation and bias the cluster assignments.",
                "tags": ["kmeans", "scaling", "clustering"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A gradient-boosted tree gets near-perfect training accuracy but much weaker validation performance after max_depth and n_estimators were increased aggressively. Which diagnosis fits best?",
                "options": [
                    "The model is overfitting and should be regularized with shallower trees, stronger leaf constraints, or more conservative boosting.",
                    "The model is underfitting and needs even deeper trees to capture the remaining structure.",
                    "Tree ensembles cannot generalize on tabular data once more than twenty features are present.",
                    "The training score is invalid because ensembles should never exceed ninety percent training accuracy.",
                ],
                "correct_answer": "The model is overfitting and should be regularized with shallower trees, stronger leaf constraints, or more conservative boosting.",
                "tags": ["gradient-boosting", "overfitting", "regularization"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A team debates random search versus exhaustive grid search over a wide hyperparameter space with only twenty trial slots. Which is generally stronger?",
                "options": [
                    "Random search because it explores more distinct regions when only a few dimensions matter most to quality.",
                    "Grid search because evenly spaced combinations always dominate random exploration under small budgets.",
                    "Grid search because random search cannot be used with continuous hyperparameters.",
                    "Both are identical if the evaluation metric is normalized between zero and one.",
                ],
                "correct_answer": "Random search because it explores more distinct regions when only a few dimensions matter most to quality.",
                "tags": ["hyperparameter-search", "random-search", "grid-search"],
            },
            {
                "difficulty": "medium",
                "style": "concept",
                "question": "Why is early stopping valuable when training boosted trees or neural networks under a validation loop?",
                "options": [
                    "It limits unnecessary fitting after validation quality stops improving and can reduce overfitting while saving compute.",
                    "It guarantees the globally optimal number of iterations for any loss landscape.",
                    "It removes the need for a validation set because stopping decisions are always stable on training loss.",
                    "It should be avoided in production systems because it makes models impossible to reproduce.",
                ],
                "correct_answer": "It limits unnecessary fitting after validation quality stops improving and can reduce overfitting while saving compute.",
                "tags": ["early-stopping", "boosting", "training"],
            },
            {
                "difficulty": "medium",
                "style": "architecture",
                "question": "A ranking service must choose between a large boosted-tree ensemble and a linear model on hashed features. What tradeoff should drive the decision?",
                "options": [
                    "The team should balance accuracy gains against serving latency, memory footprint, explainability, and operational simplicity.",
                    "The larger ensemble is always preferable because more trees guarantee better online ranking quality.",
                    "Linear models are never suitable once the problem contains any nonlinear interactions.",
                    "Model choice should be based only on which algorithm has the newer research paper.",
                ],
                "correct_answer": "The team should balance accuracy gains against serving latency, memory footprint, explainability, and operational simplicity.",
                "tags": ["ranking", "serving-latency", "model-selection"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A logistic-regression fraud detector on a 1:500 dataset predicts almost all examples as negative. Which first change is most sensible?",
                "options": [
                    "Adjust for class imbalance with threshold tuning and class weighting before concluding the model family is unusable.",
                    "Remove the rare positive class because it makes optimization numerically unstable.",
                    "Switch directly to a GAN because imbalance cannot be handled by discriminative models.",
                    "Increase the batch size until the optimizer starts predicting more positives by chance.",
                ],
                "correct_answer": "Adjust for class imbalance with threshold tuning and class weighting before concluding the model family is unusable.",
                "tags": ["class-imbalance", "logistic-regression", "thresholding"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "Bayesian optimization keeps suggesting a learning rate near 1e-7 and extremely large tree counts, producing six-hour folds for tiny metric gains. What is the strongest interpretation?",
                "options": [
                    "The search space is too broad or unconstrained, so the optimizer is exploiting impractical corners instead of useful operating points.",
                    "Bayesian optimization always converges to unusable hyperparameters for tree models in production.",
                    "Long training time proves the objective is wrong and should be replaced with accuracy immediately.",
                    "The optimizer has found the global optimum and no constraints should be added after this point.",
                ],
                "correct_answer": "The search space is too broad or unconstrained, so the optimizer is exploiting impractical corners instead of useful operating points.",
                "tags": ["bayesian-optimization", "constraints", "training-cost"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A boosted-tree pipeline uses a random train split on weekly data. The model wins offline but fails badly after a holiday regime change. What was the main modeling mistake?",
                "options": [
                    "The evaluation ignored temporal structure, so the model was not tested on the kind of future shift it would actually face.",
                    "Boosted trees cannot handle seasonality unless the target is first normalized to unit variance.",
                    "Holiday regime changes affect only linear models because tree splits are time invariant.",
                    "Random splitting is preferred for weekly data because it maximizes exposure to every holiday pattern.",
                ],
                "correct_answer": "The evaluation ignored temporal structure, so the model was not tested on the kind of future shift it would actually face.",
                "tags": ["time-series", "evaluation-design", "boosted-trees"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "A pricing model retrains nightly, but the feature distribution and label delay mean the newest labels are incomplete for the most recent days. What operational change is safest?",
                "options": [
                    "Use a stable training cutoff or delayed label window so retraining does not mix mature labels with immature outcomes.",
                    "Train on every newest row anyway because larger datasets always dominate label quality issues.",
                    "Remove the validation set because delayed labels already make the training split conservative enough.",
                    "Shift the target by one hour so the label table fills faster before nightly training.",
                ],
                "correct_answer": "Use a stable training cutoff or delayed label window so retraining does not mix mature labels with immature outcomes.",
                "tags": ["delayed-labels", "retraining", "data-maturity"],
            },
            {
                "difficulty": "hard",
                "style": "concept",
                "question": "Why can a calibrated linear model outperform a more expressive ensemble in a regulated credit workflow even if its raw AUC is slightly lower?",
                "options": [
                    "A simpler model can be easier to audit, explain, monitor, and recalibrate under policy constraints where interpretability matters.",
                    "Linear models always dominate ensembles on fairness, so the AUC difference is irrelevant.",
                    "Regulated workflows require every coefficient to be positive, which only linear models can satisfy.",
                    "Ensembles cannot be monitored in production once any categorical feature is present.",
                ],
                "correct_answer": "A simpler model can be easier to audit, explain, monitor, and recalibrate under policy constraints where interpretability matters.",
                "tags": ["model-governance", "calibration", "credit-risk"],
            },
            {
                "difficulty": "hard",
                "style": "architecture",
                "question": "An online ad ranker needs fast updates to weights every hour without full retraining on months of history. Which family is often the best fit?",
                "options": [
                    "An incremental or warm-start friendly model family that can absorb frequent updates without full expensive retrains.",
                    "A very deep transformer because it can memorize every hourly change more effectively than incremental methods.",
                    "DBSCAN because density-based clustering adapts naturally to streaming supervised labels.",
                    "A static random forest because trees become online learners once their predictions are cached.",
                ],
                "correct_answer": "An incremental or warm-start friendly model family that can absorb frequent updates without full expensive retrains.",
                "tags": ["online-learning", "warm-start", "ranking"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A gradient-descent training loop reports steady loss reduction, but the downstream business metric gets worse after each release. What should engineers suspect first?",
                "options": [
                    "The optimization objective is misaligned with the deployment metric, so lower training loss is not translating into the outcome that matters.",
                    "Loss reduction always guarantees a business metric improvement if the dataset is large enough.",
                    "The business metric is probably wrong because training loss is the most reliable production signal.",
                    "The only explanation is that the learning rate is too low for the final epochs.",
                ],
                "correct_answer": "The optimization objective is misaligned with the deployment metric, so lower training loss is not translating into the outcome that matters.",
                "tags": ["objective-misalignment", "business-metrics", "release-debugging"],
            },
        ],
    },
    {
        "topic": "Model Evaluation, Calibration, and Fairness",
        "versions": ["python311", "sklearn", "mlflow"],
        "items": [
            {
                "difficulty": "easy",
                "style": "debugging",
                "question": "A binary model on a 1:100 dataset has ROC-AUC of 0.95 but precision of 0.12 at the chosen threshold. What does that usually mean?",
                "options": [
                    "The model may rank examples well, but the current threshold creates too many false positives for this class balance.",
                    "ROC-AUC is invalid for imbalanced data, so only raw accuracy should be trusted here.",
                    "The model is broken because precision can never be much lower than ROC-AUC.",
                    "A high ROC-AUC guarantees a high precision value at every operating threshold.",
                ],
                "correct_answer": "The model may rank examples well, but the current threshold creates too many false positives for this class balance.",
                "tags": ["roc-auc", "precision", "class-imbalance"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A fraud team cares far more about false negatives than false positives. What evaluation choice should reflect that business reality first?",
                "options": [
                    "Tune the decision threshold and metrics around the asymmetric error cost instead of relying only on default thresholds.",
                    "Use raw accuracy because it treats both error types equally and removes subjective business weighting.",
                    "Disable calibration because calibrated probabilities hide false negatives in rare-event tasks.",
                    "Pick the model with the best training loss because it is threshold independent.",
                ],
                "correct_answer": "Tune the decision threshold and metrics around the asymmetric error cost instead of relying only on default thresholds.",
                "tags": ["thresholding", "cost-sensitive", "fraud"],
            },
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "Why is a calibration check useful when a model score is later used as a business probability?",
                "options": [
                    "It tests whether predicted confidence levels align with observed outcome frequencies rather than only ranking correctly.",
                    "It replaces the need for any classification metric because calibration contains all accuracy information.",
                    "It is needed only for regression models and not for probabilistic classifiers.",
                    "It guarantees fairness across all protected groups once the model is well calibrated.",
                ],
                "correct_answer": "It tests whether predicted confidence levels align with observed outcome frequencies rather than only ranking correctly.",
                "tags": ["calibration", "probabilities", "evaluation"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A retention model looks strong overall, but fails badly for newly onboarded users. What evaluation gap caused this surprise?",
                "options": [
                    "The team relied on aggregate metrics and did not inspect segment-level behavior for important subpopulations.",
                    "The model should have been evaluated only on the newest users because segmenting metrics is noisy.",
                    "Aggregate metrics always imply similar performance on every user subgroup in the same product.",
                    "The issue must come from feature scaling because subgroup metrics do not affect evaluation quality.",
                ],
                "correct_answer": "The team relied on aggregate metrics and did not inspect segment-level behavior for important subpopulations.",
                "tags": ["segmentation", "evaluation", "retention"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "Cross-validation scores vary from 0.92 to 0.45 across folds for the same classifier. What should engineers suspect first?",
                "options": [
                    "The folds may violate an important grouping or temporal structure, so the model is facing different distributions across splits.",
                    "The optimizer is definitely diverging because CV variance always comes from a bad learning rate.",
                    "Cross-validation should never be used on noisy data because fold variance invalidates the metric.",
                    "The metric implementation is wrong because valid folds should always stay within a narrow range.",
                ],
                "correct_answer": "The folds may violate an important grouping or temporal structure, so the model is facing different distributions across splits.",
                "tags": ["cross-validation", "grouping", "distribution-shift"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A search ranking model improves offline NDCG but reduces click-through rate in production. Which explanation is most plausible?",
                "options": [
                    "The offline objective may be misaligned with user behavior or production exposure, so the metric gain does not translate online.",
                    "NDCG always predicts click-through rate perfectly, so the online measurement must be broken.",
                    "Click-through rate is too noisy to compare against any offline ranking metric.",
                    "The only cause can be that the production model was calibrated after training.",
                ],
                "correct_answer": "The offline objective may be misaligned with user behavior or production exposure, so the metric gain does not translate online.",
                "tags": ["ranking", "ndcg", "online-offline-gap"],
            },
            {
                "difficulty": "medium",
                "style": "concept",
                "question": "When should PR-AUC usually be preferred over ROC-AUC?",
                "options": [
                    "When the positive class is rare and precision-recall tradeoffs matter more than average ranking over negatives.",
                    "When the dataset is balanced and the threshold is fixed at exactly 0.5 in every environment.",
                    "Only when the classifier uses logistic regression rather than tree-based learners.",
                    "Only when false positives and false negatives have exactly the same business cost.",
                ],
                "correct_answer": "When the positive class is rare and precision-recall tradeoffs matter more than average ranking over negatives.",
                "tags": ["pr-auc", "roc-auc", "imbalance"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A calibration curve shows that predictions in the 0.8 to 0.9 bucket are correct only 55 percent of the time. What is the best description?",
                "options": [
                    "The model is overconfident in that score range and needs recalibration or a better probability model.",
                    "The model is underfitting because confident buckets should always be nearly perfect.",
                    "The issue proves the class labels were shuffled because calibration affects only ranking metrics.",
                    "A calibration curve this shape means the classifier should switch from classification to regression.",
                ],
                "correct_answer": "The model is overconfident in that score range and needs recalibration or a better probability model.",
                "tags": ["calibration-curve", "overconfidence", "probabilities"],
            },
            {
                "difficulty": "medium",
                "style": "architecture",
                "question": "A lending model has a much higher false positive rate for one demographic group. What is the strongest next step?",
                "options": [
                    "Measure fairness metrics explicitly and evaluate mitigation options such as reweighting, constrained training, or calibrated post-processing.",
                    "Remove the demographic feature and assume the disparity is solved because the model can no longer observe group membership.",
                    "Freeze the current model because changing it would invalidate historical comparisons.",
                    "Lower the threshold globally and accept the disparity because false positive rates are secondary to AUC.",
                ],
                "correct_answer": "Measure fairness metrics explicitly and evaluate mitigation options such as reweighting, constrained training, or calibrated post-processing.",
                "tags": ["fairness", "equalized-odds", "lending"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A team uses training accuracy to choose hyperparameters, then reports test accuracy as the final result. Why is that invalid?",
                "options": [
                    "Hyperparameters were selected against the training set, so the final estimate is biased and the test set should remain untouched until the end.",
                    "Training accuracy is always lower than validation accuracy, so the model is being unfairly penalized.",
                    "Test accuracy can be reported only for unsupervised models that were not tuned on labels.",
                    "The problem is minor because the test set still acts like an outer cross-validation loop.",
                ],
                "correct_answer": "Hyperparameters were selected against the training set, so the final estimate is biased and the test set should remain untouched until the end.",
                "tags": ["hyperparameter-tuning", "test-leakage", "evaluation-protocol"],
            },
            {
                "difficulty": "hard",
                "style": "scenario",
                "question": "A medical triage model has similar ROC-AUC across hospitals, but calibration differs sharply by site. Why is that operationally important?",
                "options": [
                    "If site-level probability estimates are off, the same score threshold can drive very different decisions and workloads across hospitals.",
                    "Calibration differences do not matter once ROC-AUC is stable because ranking is the only production property that counts.",
                    "Probability calibration matters only for marketing models and not for risk-scoring systems.",
                    "The issue can be ignored because hospitals will manually adjust scores during use.",
                ],
                "correct_answer": "If site-level probability estimates are off, the same score threshold can drive very different decisions and workloads across hospitals.",
                "tags": ["site-calibration", "thresholds", "risk-scoring"],
            },
            {
                "difficulty": "hard",
                "style": "concept",
                "question": "Why can a model with better log loss but slightly worse top-line accuracy still be preferable in production?",
                "options": [
                    "Its probabilities may be better ordered and calibrated for downstream decisioning even if the default threshold yields fewer exact matches.",
                    "Accuracy is not a real metric once log loss is available, so it should always be ignored.",
                    "Log loss improves only when the model has fewer parameters than a higher-accuracy alternative.",
                    "A lower log loss guarantees the model is fairer across all subgroups.",
                ],
                "correct_answer": "Its probabilities may be better ordered and calibrated for downstream decisioning even if the default threshold yields fewer exact matches.",
                "tags": ["log-loss", "accuracy", "decisioning"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A fraud review queue doubles overnight after a threshold update, even though model AUC is unchanged. What changed most likely caused the incident?",
                "options": [
                    "The operating threshold was moved without recalculating the precision-recall tradeoff under the current class distribution.",
                    "AUC drifted in production because thresholds directly alter rank ordering.",
                    "The model weights were corrupted because queue size and AUC can never diverge.",
                    "The queue increase proves the labels became balanced after the threshold change.",
                ],
                "correct_answer": "The operating threshold was moved without recalculating the precision-recall tradeoff under the current class distribution.",
                "tags": ["thresholding", "operations", "fraud-review"],
            },
            {
                "difficulty": "hard",
                "style": "scenario",
                "question": "An abuse classifier shows stable offline metrics, but a new policy changes which errors are expensive. What is the correct response?",
                "options": [
                    "Re-evaluate the decision threshold and possibly the training objective against the updated cost function rather than relying on old metrics.",
                    "Keep the model unchanged because offline metrics are stable and business policy should not affect thresholds.",
                    "Increase regularization so the model becomes less sensitive to policy changes over time.",
                    "Switch to unsupervised detection because policy-aware thresholds make supervised models too subjective.",
                ],
                "correct_answer": "Re-evaluate the decision threshold and possibly the training objective against the updated cost function rather than relying on old metrics.",
                "tags": ["cost-sensitive", "policy-change", "thresholding"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "A model is retrained every week and monitored only with aggregate accuracy. A niche but high-value merchant segment degrades for three months before anyone notices. What was missing?",
                "options": [
                    "Segment-aware monitoring and alerting tied to important business cohorts, not just one aggregate metric.",
                    "A lower learning rate because weekly retraining usually hides subgroup drift.",
                    "A larger validation set because segment problems always disappear with more samples.",
                    "A confusion matrix because aggregate accuracy cannot coexist with any subgroup reporting.",
                ],
                "correct_answer": "Segment-aware monitoring and alerting tied to important business cohorts, not just one aggregate metric.",
                "tags": ["monitoring", "segments", "merchant-risk"],
            },
        ],
    },
    {
        "topic": "Deep Learning Training and Troubleshooting",
        "versions": ["python311", "pytorch", "transformers"],
        "items": [
            {
                "difficulty": "easy",
                "style": "debugging",
                "question": "A PyTorch training run starts producing NaN loss after gradient norms spike to very large values. What should be tried first?",
                "options": [
                    "Apply gradient clipping and inspect whether the learning rate or loss scaling is too aggressive.",
                    "Increase batch size to the maximum possible value because larger batches prevent numerical overflow.",
                    "Remove regularization because NaN loss always comes from too much weight decay.",
                    "Switch every activation to sigmoid because bounded outputs eliminate all training instability.",
                ],
                "correct_answer": "Apply gradient clipping and inspect whether the learning rate or loss scaling is too aggressive.",
                "tags": ["gradient-clipping", "nan-loss", "pytorch"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A network using ReLU stops activating several neurons permanently after a few updates. What architectural variant helps most directly?",
                "options": [
                    "Use Leaky ReLU or a similar nonzero-negative-slope activation so gradients can still flow for negative inputs.",
                    "Replace ReLU with hard thresholding because zero gradients make the network more stable.",
                    "Move every bias term to the output layer so hidden units never enter the negative regime.",
                    "Switch to batch size one because dying activations happen only in large minibatches.",
                ],
                "correct_answer": "Use Leaky ReLU or a similar nonzero-negative-slope activation so gradients can still flow for negative inputs.",
                "tags": ["relu", "activations", "training-stability"],
            },
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "Why do residual connections make very deep networks easier to train?",
                "options": [
                    "They provide shortcut paths that improve gradient flow and make it easier to learn near-identity mappings when needed.",
                    "They cut the parameter count in half, so optimization becomes convex after enough layers are skipped.",
                    "They remove the need for normalization because every residual branch is already mean centered.",
                    "They guarantee the globally optimal solution once the network depth exceeds fifty layers.",
                ],
                "correct_answer": "They provide shortcut paths that improve gradient flow and make it easier to learn near-identity mappings when needed.",
                "tags": ["residual-connections", "optimization", "deep-networks"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A training job is resumed from checkpoint, but loss jumps sharply even though model weights were restored. What commonly gets missed?",
                "options": [
                    "Optimizer and scheduler state may not have been restored, so learning dynamics resumed from inconsistent settings.",
                    "Weights alone are sufficient, and any loss jump proves the dataset order changed permanently.",
                    "Only the random seed matters after resuming because optimizers recompute their state immediately.",
                    "The issue shows that checkpointing should exclude all momentum buffers for stability.",
                ],
                "correct_answer": "Optimizer and scheduler state may not have been restored, so learning dynamics resumed from inconsistent settings.",
                "tags": ["checkpointing", "optimizer-state", "resume-training"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A mixed-precision training job is fast, but validation quality drifts and some steps overflow intermittently. What should engineers inspect first?",
                "options": [
                    "Loss scaling, unstable layers, and whether certain operations should remain in full precision.",
                    "Only the GPU temperature, because floating-point overflow under AMP is usually a cooling problem.",
                    "The dataloader shuffle seed, because mixed precision changes label ordering across epochs.",
                    "The batch size alone, because AMP overflow cannot be related to model architecture.",
                ],
                "correct_answer": "Loss scaling, unstable layers, and whether certain operations should remain in full precision.",
                "tags": ["amp", "mixed-precision", "overflow"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A BERT fine-tune on 5,000 labeled examples underperforms a TF-IDF logistic baseline. Which adjustment is most sensible first?",
                "options": [
                    "Reduce the fine-tuning aggressiveness by lowering the learning rate, freezing more layers, or using a smaller pretrained model.",
                    "Increase the tokenizer vocabulary size because small datasets always need more subword pieces.",
                    "Switch immediately to a GAN because transformer fine-tuning is unreliable on labeled tasks.",
                    "Discard the pretrained model because classical baselines always dominate under ten thousand examples.",
                ],
                "correct_answer": "Reduce the fine-tuning aggressiveness by lowering the learning rate, freezing more layers, or using a smaller pretrained model.",
                "tags": ["bert", "fine-tuning", "small-data"],
            },
            {
                "difficulty": "medium",
                "style": "concept",
                "question": "What is the primary role of batch normalization during deep network training?",
                "options": [
                    "It stabilizes optimization by normalizing intermediate activations and often permits faster learning with better-conditioned updates.",
                    "It permanently stores the best batch for replay during later epochs.",
                    "It guarantees the model will generalize if training loss reaches zero quickly.",
                    "It is used only at inference time to reduce prediction latency on GPUs.",
                ],
                "correct_answer": "It stabilizes optimization by normalizing intermediate activations and often permits faster learning with better-conditioned updates.",
                "tags": ["batchnorm", "optimization", "training"],
            },
            {
                "difficulty": "medium",
                "style": "architecture",
                "question": "A multimodal model must train under a fixed memory budget. What architectural question matters before simply widening the backbone?",
                "options": [
                    "Whether the added capacity is better spent on smarter fusion, gradient checkpointing, or sequence reduction rather than just larger hidden states.",
                    "Whether GPU memory can be bypassed completely by switching all tensors to Python lists.",
                    "Whether the backbone width can be increased without affecting optimization or communication at all.",
                    "Whether memory budgets matter only during inference and can be ignored while training.",
                ],
                "correct_answer": "Whether the added capacity is better spent on smarter fusion, gradient checkpointing, or sequence reduction rather than just larger hidden states.",
                "tags": ["multimodal", "memory-budget", "architecture"],
            },
            {
                "difficulty": "medium",
                "style": "operations",
                "question": "GPU utilization is low even though the model is large and the batch size is reasonable. What bottleneck should engineers check first?",
                "options": [
                    "The input pipeline and dataloader, because slow host-side decoding or feature preparation can starve the accelerator.",
                    "The optimizer choice, because Adam always caps utilization below fifty percent on modern hardware.",
                    "The random seed, because reproducible training disables overlap between compute and data loading.",
                    "The validation metric, because GPU utilization depends mostly on whether ROC-AUC is computed per step.",
                ],
                "correct_answer": "The input pipeline and dataloader, because slow host-side decoding or feature preparation can starve the accelerator.",
                "tags": ["gpu-utilization", "dataloader", "throughput"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A distributed training job is reproducible on one node but diverges subtly across multi-node runs even with seeds fixed. What is the best explanation?",
                "options": [
                    "Not every operation or communication path is deterministic across hardware and parallel execution, so seeding alone is insufficient.",
                    "Once seeds are fixed, any drift proves the labels are being shuffled differently between nodes by the loss function.",
                    "Distributed runs always become deterministic after the first warmup epoch if gradient clipping is enabled.",
                    "The issue can only come from batch normalization statistics and never from data ordering or kernels.",
                ],
                "correct_answer": "Not every operation or communication path is deterministic across hardware and parallel execution, so seeding alone is insufficient.",
                "tags": ["distributed-training", "reproducibility", "determinism"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A gradient accumulation setup forgets to divide the loss before backward passes. What production symptom is most likely?",
                "options": [
                    "The effective update becomes too large relative to the intended batch size, often making optimization unstable or inconsistent.",
                    "Nothing changes because gradient accumulation and batch scaling are mathematically identical without any extra care.",
                    "The model simply trains slower while preserving the same gradient magnitude and convergence path.",
                    "The issue affects only validation metrics and not the actual optimization dynamics.",
                ],
                "correct_answer": "The effective update becomes too large relative to the intended batch size, often making optimization unstable or inconsistent.",
                "tags": ["gradient-accumulation", "loss-scaling", "optimization"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A GAN begins generating only a narrow family of images after several epochs, even though discriminator loss looks healthy. What failure mode is this?",
                "options": [
                    "Mode collapse, where the generator maps many latent inputs to a limited set of outputs instead of covering the target distribution.",
                    "Label smoothing, where the discriminator becomes too uncertain to guide the generator.",
                    "Gradient checkpointing, where stored activations distort the latent space during replay.",
                    "Teacher forcing, where the generator starts copying labels from the discriminator.",
                ],
                "correct_answer": "Mode collapse, where the generator maps many latent inputs to a limited set of outputs instead of covering the target distribution.",
                "tags": ["gan", "mode-collapse", "generative-models"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A transformer classifier suddenly trains much slower after sequence length was doubled. Which complexity change matters most?",
                "options": [
                    "Self-attention cost grows roughly quadratically with sequence length, so doubling tokens can create far more than double the work.",
                    "Transformer cost grows linearly with token count, so the slowdown must come only from the tokenizer.",
                    "The sequence length change affects memory but not compute because attention is cached during training.",
                    "Quadratic scaling applies only to decoder models and not to encoder-based classifiers.",
                ],
                "correct_answer": "Self-attention cost grows roughly quadratically with sequence length, so doubling tokens can create far more than double the work.",
                "tags": ["transformers", "attention", "sequence-length"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A frozen-base fine-tune suddenly forgets its pretrained capability after the final layers are unfrozen and trained with a large rate. What happened?",
                "options": [
                    "The update likely overwrote useful pretrained representations through overly aggressive fine-tuning, a form of catastrophic forgetting.",
                    "Unfreezing layers always improves transfer quality, so the drop must come only from validation noise.",
                    "Catastrophic forgetting can occur only in reinforcement learning and not in supervised fine-tuning.",
                    "Large learning rates affect only convergence speed and cannot damage pretrained features.",
                ],
                "correct_answer": "The update likely overwrote useful pretrained representations through overly aggressive fine-tuning, a form of catastrophic forgetting.",
                "tags": ["fine-tuning", "catastrophic-forgetting", "transfer-learning"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "A sequence model must fit within strict GPU memory and deployment latency targets. Which production tactic is often strongest before buying more hardware?",
                "options": [
                    "Use a combination of smaller model variants, sequence truncation policy, gradient checkpointing, or distillation based on the real bottleneck.",
                    "Increase hidden size until utilization is high enough to justify the hardware cost.",
                    "Disable evaluation completely so all memory is available for the forward pass.",
                    "Move labels to CPU memory because that is usually the largest contributor to sequence-model latency.",
                ],
                "correct_answer": "Use a combination of smaller model variants, sequence truncation policy, gradient checkpointing, or distillation based on the real bottleneck.",
                "tags": ["memory-optimization", "distillation", "latency"],
            },
        ],
    },
    {
        "topic": "LLMs, Embeddings, and RAG Systems",
        "versions": ["python311", "transformers", "mlflow"],
        "items": [
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "A support assistant retrieves chunks from policy documents before answering. Why can retrieval quality matter more than prompt wording in many enterprise RAG failures?",
                "options": [
                    "If the retriever surfaces weak or irrelevant evidence, even a strong prompt is forced to reason over the wrong context.",
                    "Prompt wording fully determines factuality, so retrieval mistakes are usually masked by the language model.",
                    "RAG quality depends only on model temperature because retrieval is a deterministic preprocessing step.",
                    "Once documents are chunked, every chunk has equal answer value and prompt style becomes the only differentiator.",
                ],
                "correct_answer": "If the retriever surfaces weak or irrelevant evidence, even a strong prompt is forced to reason over the wrong context.",
                "tags": ["rag", "retrieval-quality", "grounding"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A company updates compliance policies daily. Which answer-generation strategy is usually strongest before considering expensive fine-tuning?",
                "options": [
                    "Use retrieval-augmented generation so the model can ground answers in the latest source documents without retraining the base model each day.",
                    "Fully fine-tune the model after each policy change because RAG cannot handle structured enterprise documents.",
                    "Store the policies only inside the system prompt because that scales better than document retrieval for daily updates.",
                    "Disable citations so the model can answer more flexibly when the policy text changes often.",
                ],
                "correct_answer": "Use retrieval-augmented generation so the model can ground answers in the latest source documents without retraining the base model each day.",
                "tags": ["rag", "policy-updates", "fine-tuning"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A RAG bot retrieves the right document set, but answers still cite outdated refund rules. Investigation shows chunk metadata was not preserved during indexing. What is the most likely impact?",
                "options": [
                    "The system cannot reliably filter or rank the most current chunks, so stale passages can dominate the final context despite good document recall.",
                    "Metadata loss matters only for dashboards because the language model reads raw text and ignores ranking decisions.",
                    "The issue proves the embedding model should be replaced with a larger decoder-only model immediately.",
                    "Without metadata, the retriever automatically falls back to chronological ordering of source text inside the vector store.",
                ],
                "correct_answer": "The system cannot reliably filter or rank the most current chunks, so stale passages can dominate the final context despite good document recall.",
                "tags": ["metadata", "rag-debugging", "ranking"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A product team wants to improve answers for a narrow internal workflow with fewer than 5,000 labeled examples. Which path is often the most defensible first step?",
                "options": [
                    "Strengthen retrieval, prompt structure, and evaluation before committing to fine-tuning on a small proprietary dataset.",
                    "Skip retrieval entirely because enterprise workflows are always better served by full supervised fine-tuning.",
                    "Train a larger embedding model from scratch because small labeled sets are ideal for representation learning from first principles.",
                    "Increase output temperature because low-diversity answers are the main cause of narrow workflow failures.",
                ],
                "correct_answer": "Strengthen retrieval, prompt structure, and evaluation before committing to fine-tuning on a small proprietary dataset.",
                "tags": ["prompting", "fine-tuning", "evaluation"],
            },
            {
                "difficulty": "medium",
                "style": "concept",
                "question": "Why is mixing vectors from two embedding model versions inside the same ANN index risky?",
                "options": [
                    "Similarity scores become inconsistent because the vectors may no longer share the same geometry or calibration assumptions.",
                    "ANN indexes are version aware and automatically normalize embeddings from different encoder families.",
                    "Only Euclidean indexes are affected because cosine similarity removes every representation mismatch.",
                    "Embedding version mismatches matter only when the vector dimensionality changes between releases.",
                ],
                "correct_answer": "Similarity scores become inconsistent because the vectors may no longer share the same geometry or calibration assumptions.",
                "tags": ["embeddings", "indexing", "representation-consistency"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "Offline answer-similarity scores improved after a retriever change, but live users report that the assistant repeats near-duplicate evidence and misses broader context. What failure is most likely?",
                "options": [
                    "The retriever improved lexical matching while collapsing result diversity, so the context window is crowded with redundant chunks instead of complementary evidence.",
                    "The production issue proves answer-similarity metrics are always invalid for every generative system.",
                    "Duplicate evidence is expected because rerankers intentionally ignore semantic overlap once recall increases.",
                    "The reports imply the model temperature is too low, not that retrieval diversity regressed.",
                ],
                "correct_answer": "The retriever improved lexical matching while collapsing result diversity, so the context window is crowded with redundant chunks instead of complementary evidence.",
                "tags": ["retrieval-diversity", "evaluation", "live-traffic"],
            },
            {
                "difficulty": "hard",
                "style": "scenario",
                "question": "An enterprise assistant must answer from fast-changing policy documents and also perform domain-specific phrasing. Which overall strategy is strongest?",
                "options": [
                    "Keep the factual layer grounded through retrieval and use prompt or light adaptation only for response style and task framing.",
                    "Fully fine-tune the base model on policy text and disable retrieval so model behavior stays simpler to explain.",
                    "Use only prompt engineering because retrieval and fine-tuning should never be combined in one enterprise system.",
                    "Store policy summaries in the system prompt and rely on hallucination filters instead of source grounding.",
                ],
                "correct_answer": "Keep the factual layer grounded through retrieval and use prompt or light adaptation only for response style and task framing.",
                "tags": ["rag", "fine-tuning-strategy", "enterprise-assistants"],
            },
            {
                "difficulty": "hard",
                "style": "architecture",
                "question": "A multi-tenant RAG platform serves many customers with overlapping terminology but strict data isolation. Which architecture is strongest?",
                "options": [
                    "Partition retrieval or apply tenant-aware filters and identifiers so ranking stays semantically useful without cross-tenant evidence leakage.",
                    "Use one shared global index without tenant metadata because semantic search naturally separates customers with different jargon.",
                    "Replicate the entire foundation model per tenant because retrieval isolation cannot be enforced at the vector-store layer.",
                    "Disable embeddings and rely only on keyword search because vector search cannot support access boundaries.",
                ],
                "correct_answer": "Partition retrieval or apply tenant-aware filters and identifiers so ranking stays semantically useful without cross-tenant evidence leakage.",
                "tags": ["multi-tenant", "access-control", "vector-search"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "A prompt evaluation suite reports steady gains every week, but the same 300 annotated prompts are reused for ranking experiments. Why is that operationally dangerous?",
                "options": [
                    "The team is overfitting decisions to a fixed evaluation slice, so the reported gains can reflect benchmark tuning rather than broader user benefit.",
                    "Prompt evaluation sets must be regenerated daily because fixed evaluation data is invalid for language systems.",
                    "The issue matters only if the prompts include personally identifiable information or regulated text fields.",
                    "Repeated prompt scoring is harmless because generative metrics are already too noisy to overfit in practice.",
                ],
                "correct_answer": "The team is overfitting decisions to a fixed evaluation slice, so the reported gains can reflect benchmark tuning rather than broader user benefit.",
                "tags": ["prompt-evaluation", "benchmark-overfitting", "operations"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "An organization rolls out a new embedding model gradually, but only half of the corpus is re-embedded before traffic is shifted. What is the main operational risk?",
                "options": [
                    "Live retrieval quality can become inconsistent because queries are compared against a mixed corpus whose vectors were produced by incompatible encoders.",
                    "Partial re-embedding is always safe because ANN stores normalize vector spaces during index refresh automatically.",
                    "The rollout risk is limited to slower indexing throughput and does not affect answer correctness.",
                    "Only reranking models are sensitive to phased rollout because first-stage retrieval ignores vector geometry.",
                ],
                "correct_answer": "Live retrieval quality can become inconsistent because queries are compared against a mixed corpus whose vectors were produced by incompatible encoders.",
                "tags": ["embedding-rollout", "index-refresh", "operations"],
            },
        ],
    },
    {
        "topic": "NLP and Text Systems",
        "versions": ["python311", "transformers", "sklearn"],
        "items": [
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "A support-ticket classifier reports strong overall accuracy, but the rare escalation class is often missed. Why is macro-averaged evaluation useful here?",
                "options": [
                    "It gives each class comparable weight, so failure on a rare but important class is not hidden by majority traffic.",
                    "It forces the model to predict every class equally often, which automatically fixes class imbalance.",
                    "Macro metrics are preferred only when the dataset has exactly the same number of examples per class.",
                    "It replaces the need for a confusion matrix by encoding every error type into one threshold-independent score.",
                ],
                "correct_answer": "It gives each class comparable weight, so failure on a rare but important class is not hidden by majority traffic.",
                "tags": ["macro-metrics", "class-imbalance", "text-classification"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A sentiment model trained on well-formed reviews is deployed on noisy chat transcripts with abbreviations and typos. What should engineers expect first?",
                "options": [
                    "Performance can drop because the serving text distribution differs materially from the language patterns seen during training.",
                    "The model should improve because noisier text usually contains stronger sentiment cues than edited reviews.",
                    "Tokenizers make domain shift irrelevant as long as subword vocabularies are reused at inference time.",
                    "The issue affects only generation tasks and not classification pipelines built on pretrained encoders.",
                ],
                "correct_answer": "Performance can drop because the serving text distribution differs materially from the language patterns seen during training.",
                "tags": ["domain-shift", "chat-data", "text-classification"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A weakly supervised intent model looks strong offline, but manual review shows many labels were copied from brittle regex rules with systematic mistakes. What is the real problem?",
                "options": [
                    "The model is learning from noisy pseudo-labels that encode the rule errors, so offline validation can inherit the same bias instead of reflecting true task quality.",
                    "Weak supervision always beats human labeling because heuristics are more consistent than annotators.",
                    "Regex-generated labels become ground truth automatically once the dataset is large enough for a transformer model.",
                    "The issue can be fixed only by increasing the hidden size of the classifier head at fine-tuning time.",
                ],
                "correct_answer": "The model is learning from noisy pseudo-labels that encode the rule errors, so offline validation can inherit the same bias instead of reflecting true task quality.",
                "tags": ["weak-supervision", "label-noise", "validation"],
            },
            {
                "difficulty": "medium",
                "style": "architecture",
                "question": "A multilingual ticket router serves ten languages but only two have large labeled datasets. Which design is most defensible first?",
                "options": [
                    "Start with a shared multilingual encoder and language-aware evaluation so low-resource languages benefit from transfer while still being monitored separately.",
                    "Train ten isolated models immediately because multilingual transfer is never reliable in production routing systems.",
                    "Translate everything to English and discard the original language because routing quality depends only on label volume.",
                    "Use character-level bag-of-words models only because pretrained multilingual encoders are too opaque to deploy safely.",
                ],
                "correct_answer": "Start with a shared multilingual encoder and language-aware evaluation so low-resource languages benefit from transfer while still being monitored separately.",
                "tags": ["multilingual", "transfer-learning", "routing"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A complaint classifier handles short tickets well, but recall collapses on long multi-paragraph cases after deployment. Logs show most requests hit the tokenizer max length. What is the likely cause?",
                "options": [
                    "Important evidence is being truncated before the model sees it, so long-form tickets lose the signal needed for correct classification.",
                    "Long documents always improve recall because they provide more context than the model can misuse.",
                    "Tokenizer truncation affects latency only and cannot explain a class-specific recall drop.",
                    "The issue proves attention masks are being applied in the wrong direction during batching.",
                ],
                "correct_answer": "Important evidence is being truncated before the model sees it, so long-form tickets lose the signal needed for correct classification.",
                "tags": ["truncation", "long-documents", "recall"],
            },
            {
                "difficulty": "hard",
                "style": "scenario",
                "question": "A text classifier trained on public product reviews is being adapted to enterprise support tickets. Which evaluation approach is strongest before rollout?",
                "options": [
                    "Build a domain-specific validation slice from support tickets and compare errors by intent, severity, and message length instead of trusting the old review benchmark.",
                    "Reuse the product-review benchmark because domain transfer quality is usually reflected by the original validation set.",
                    "Skip validation if the pretrained model already exceeds a strong zero-shot leaderboard score on open benchmarks.",
                    "Focus only on aggregate accuracy because ticket routing decisions are insensitive to segment-level drift.",
                ],
                "correct_answer": "Build a domain-specific validation slice from support tickets and compare errors by intent, severity, and message length instead of trusting the old review benchmark.",
                "tags": ["domain-adaptation", "evaluation", "support-tickets"],
            },
            {
                "difficulty": "hard",
                "style": "concept",
                "question": "Why can subword tokenization still struggle on specialized enterprise jargon even when the base model is pretrained on huge corpora?",
                "options": [
                    "Rare domain terms may be split into awkward fragments that weaken semantic representation and hurt downstream generalization without domain adaptation.",
                    "Subword tokenization guarantees perfect handling of every new domain term because pieces are compositional by definition.",
                    "Enterprise jargon matters only for decoder models and not for encoders used in classification tasks.",
                    "Tokenization quality becomes irrelevant once the fine-tuning dataset reaches a few thousand labeled examples.",
                ],
                "correct_answer": "Rare domain terms may be split into awkward fragments that weaken semantic representation and hurt downstream generalization without domain adaptation.",
                "tags": ["tokenization", "domain-jargon", "representation"],
            },
        ],
    },
    {
        "topic": "Computer Vision and Multimodal Systems",
        "versions": ["python311", "pytorch"],
        "items": [
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "An inspection system must count tiny surface defects and localize each one precisely. Why is plain image classification usually insufficient?",
                "options": [
                    "Classification predicts only image-level labels, while the use case needs object-level location or segmentation to separate multiple defects.",
                    "Classification cannot be used on industrial images unless they are first converted to grayscale.",
                    "Localization is unnecessary because defect counts can be inferred from a single confidence score.",
                    "Object detectors are preferred only when the images contain natural scenes rather than manufactured parts.",
                ],
                "correct_answer": "Classification predicts only image-level labels, while the use case needs object-level location or segmentation to separate multiple defects.",
                "tags": ["computer-vision", "detection", "inspection"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "An image-segmentation model trains on augmented images, but masks were rotated with bilinear interpolation and now have blurry class boundaries. What is the likely impact?",
                "options": [
                    "The target masks are being corrupted by invalid intermediate label values, which can teach the model inconsistent boundaries.",
                    "Interpolation choice affects image quality only and not the supervision signal used for segmentation.",
                    "Blurry masks improve robustness automatically because the model learns smoother edges during training.",
                    "The issue matters only for binary segmentation and not for multiclass pixel labeling tasks.",
                ],
                "correct_answer": "The target masks are being corrupted by invalid intermediate label values, which can teach the model inconsistent boundaries.",
                "tags": ["segmentation", "augmentation", "label-integrity"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A retail shelf system must both find products and separate overlapping packages. Which modeling direction is strongest first?",
                "options": [
                    "Use detection if coarse boxes are sufficient, but move to instance segmentation when overlapping boundaries drive the business outcome.",
                    "Always prefer image classification because shelf layouts implicitly reveal all individual products.",
                    "Choose semantic segmentation only, because overlap never matters once class labels are known.",
                    "Use OCR alone because product localization quality is determined entirely by readable package text.",
                ],
                "correct_answer": "Use detection if coarse boxes are sufficient, but move to instance segmentation when overlapping boundaries drive the business outcome.",
                "tags": ["retail-vision", "instance-segmentation", "detection"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A vision model performs well offline, but production accuracy collapses after deployment to a service that reads frames in BGR while training used RGB. What happened?",
                "options": [
                    "The channel order changed at serving time, creating a silent preprocessing skew between training and production inputs.",
                    "Color-channel order does not matter once convolutional filters are learned on enough data.",
                    "The problem must come from batch normalization statistics because channel order cannot affect inference directly.",
                    "BGR versus RGB changes latency only, not representation quality, in modern vision backbones.",
                ],
                "correct_answer": "The channel order changed at serving time, creating a silent preprocessing skew between training and production inputs.",
                "tags": ["preprocessing-skew", "rgb-bgr", "production-debugging"],
            },
            {
                "difficulty": "hard",
                "style": "scenario",
                "question": "A document-understanding model is accurate enough, but inference latency is above SLA. Which response is usually strongest before collecting a much larger dataset?",
                "options": [
                    "Evaluate smaller backbones, distillation, or region-of-interest reduction so the latency bottleneck is reduced without blindly expanding training scope.",
                    "Increase image resolution further because higher detail is the standard first fix for latency problems.",
                    "Duplicate the model across more threads because single-request latency is determined only by concurrency settings.",
                    "Replace OCR with manual annotations because automated document models rarely meet enterprise SLAs.",
                ],
                "correct_answer": "Evaluate smaller backbones, distillation, or region-of-interest reduction so the latency bottleneck is reduced without blindly expanding training scope.",
                "tags": ["latency", "distillation", "document-ai"],
            },
            {
                "difficulty": "hard",
                "style": "architecture",
                "question": "A multimodal claims system combines OCR text with page images. Which architecture concern matters most before deployment?",
                "options": [
                    "The system must preserve alignment between visual regions and extracted text so downstream reasoning is grounded in consistent evidence across modalities.",
                    "Visual and text pipelines can be designed independently because multimodal models fuse representations automatically without alignment.",
                    "OCR should be disabled during deployment because image encoders already contain every document token implicitly.",
                    "Alignment matters only for training and can be ignored once the inference model is frozen.",
                ],
                "correct_answer": "The system must preserve alignment between visual regions and extracted text so downstream reasoning is grounded in consistent evidence across modalities.",
                "tags": ["multimodal", "ocr", "alignment"],
            },
        ],
    },
    {
        "topic": "Ranking, Retrieval, and Recommendation",
        "versions": ["python311", "sklearn", "pytorch"],
        "items": [
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "A ranking team reports strong overall AUC, but users complain that top results feel poor. Why can that happen?",
                "options": [
                    "AUC measures pairwise ordering broadly, while top-of-list quality may still be weak if the metric is not aligned with early-rank business objectives.",
                    "AUC directly optimizes top-one precision, so user complaints usually mean the feedback data is fabricated.",
                    "Ranking quality cannot degrade when AUC improves because pairwise metrics fully determine every top-k outcome.",
                    "The issue arises only in recommendation systems that use content features instead of collaborative signals.",
                ],
                "correct_answer": "AUC measures pairwise ordering broadly, while top-of-list quality may still be weak if the metric is not aligned with early-rank business objectives.",
                "tags": ["ranking-metrics", "auc", "top-k"],
            },
            {
                "difficulty": "medium",
                "style": "scenario",
                "question": "A recommendation system struggles to surface fresh items that have little interaction history. Which strategy is usually most defensible?",
                "options": [
                    "Use content or metadata features plus controlled exploration so new items can compete before enough behavior data accumulates.",
                    "Hide new items until they collect a full week of clicks so the ranker sees only stable behavior signals.",
                    "Increase popularity weighting because cold-start items need stronger historical priors than mature items.",
                    "Disable candidate generation and rank every item globally so fresh content has equal exposure at all times.",
                ],
                "correct_answer": "Use content or metadata features plus controlled exploration so new items can compete before enough behavior data accumulates.",
                "tags": ["cold-start", "recommendation", "exploration"],
            },
            {
                "difficulty": "medium",
                "style": "architecture",
                "question": "A marketplace must rank millions of items under tight latency. Why is a two-stage system common?",
                "options": [
                    "A fast candidate generator narrows the set before a richer ranker spends compute on a much smaller shortlist.",
                    "Two-stage ranking is required only when the first model is linear and the second is neural.",
                    "Candidate generation is used mainly to increase randomness rather than to control compute or recall.",
                    "Single-stage ranking scales better because modern accelerators remove the cost of scoring large corpora online.",
                ],
                "correct_answer": "A fast candidate generator narrows the set before a richer ranker spends compute on a much smaller shortlist.",
                "tags": ["two-stage-ranking", "latency", "candidate-generation"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A retrieval system switches from cosine similarity to raw dot-product scoring without normalizing vectors, and suddenly popular dense vectors dominate results. What is the likely cause?",
                "options": [
                    "Vector magnitude now influences ranking, so items with larger norms can win even when semantic direction is a weaker match.",
                    "Dot-product scoring always removes popularity bias because it treats every vector dimension independently.",
                    "Normalization affects only ANN memory usage and cannot change retrieval ordering in practice.",
                    "The issue proves cosine similarity should be avoided whenever embeddings are trained with contrastive loss.",
                ],
                "correct_answer": "Vector magnitude now influences ranking, so items with larger norms can win even when semantic direction is a weaker match.",
                "tags": ["retrieval", "dot-product", "normalization"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "A ranking canary improves click-through rate but reduces downstream conversion quality. What is the strongest operational interpretation?",
                "options": [
                    "The online objective is misaligned with the business outcome, so the ranker is likely promoting click-attractive results that do not create durable value.",
                    "Any rise in click-through rate proves the new ranking policy is healthier than the baseline by definition.",
                    "Conversion drops are expected in canaries because smaller traffic slices cannot measure revenue-sensitive behavior.",
                    "The problem is usually caused by stale model artifacts rather than by objective mismatch or feedback loops.",
                ],
                "correct_answer": "The online objective is misaligned with the business outcome, so the ranker is likely promoting click-attractive results that do not create durable value.",
                "tags": ["objective-alignment", "ctr", "conversion"],
            },
        ],
    },
    {
        "topic": "MLOps, Deployment, and Monitoring",
        "versions": ["python311", "mlflow", "sklearn", "pytorch"],
        "items": [
            {
                "difficulty": "easy",
                "style": "concept",
                "question": "Why is experiment lineage important in an ML platform even after a model appears to perform well?",
                "options": [
                    "It lets engineers trace predictions back to the exact code, data, parameters, and artifacts that produced a model when regressions appear later.",
                    "Lineage is optional once a model reaches production because only live metrics matter after deployment.",
                    "Experiment lineage is used mainly to reduce GPU memory consumption during distributed training.",
                    "Tracking lineage replaces the need for model validation because reproducibility guarantees correctness.",
                ],
                "correct_answer": "It lets engineers trace predictions back to the exact code, data, parameters, and artifacts that produced a model when regressions appear later.",
                "tags": ["mlflow", "lineage", "reproducibility"],
            },
            {
                "difficulty": "easy",
                "style": "scenario",
                "question": "A high-risk underwriting model needs to be evaluated in production before affecting decisions. Which rollout pattern is strongest first?",
                "options": [
                    "Use shadow deployment so predictions can be observed against live traffic before the model starts influencing outcomes.",
                    "Deploy directly to all users because offline validation already removed the need for production comparison.",
                    "Use canary rollout immediately and suppress logging until the model proves profitable.",
                    "Skip rollout stages and compare only monthly business KPIs after the full launch.",
                ],
                "correct_answer": "Use shadow deployment so predictions can be observed against live traffic before the model starts influencing outcomes.",
                "tags": ["shadow-deployment", "risk-control", "rollout"],
            },
            {
                "difficulty": "medium",
                "style": "debugging",
                "question": "A model server loads the latest weights correctly, but predictions drift because the preprocessing artifact was not updated with the same release. What type of failure is this?",
                "options": [
                    "A model-artifact mismatch where serving still applies an outdated feature transform that no longer matches the trained model inputs.",
                    "A normal warmup effect that disappears automatically once the inference cache fills for the new model.",
                    "A harmless monitoring discrepancy because preprocessing artifacts do not affect model semantics after export.",
                    "A GPU scheduling problem that should be addressed only through larger batch sizes at inference time.",
                ],
                "correct_answer": "A model-artifact mismatch where serving still applies an outdated feature transform that no longer matches the trained model inputs.",
                "tags": ["artifact-versioning", "serving-skew", "debugging"],
            },
            {
                "difficulty": "medium",
                "style": "concept",
                "question": "Why is it important to distinguish data drift from concept drift when monitoring a deployed model?",
                "options": [
                    "They suggest different remedies: one reflects changing inputs, while the other reflects a changing relationship between inputs and outcomes.",
                    "They are interchangeable terms, so a single aggregate drift alarm is enough for remediation planning.",
                    "Concept drift occurs only in unsupervised models, while data drift occurs only in supervised models.",
                    "Both can be fixed in the same way by increasing the inference batch size during monitoring windows.",
                ],
                "correct_answer": "They suggest different remedies: one reflects changing inputs, while the other reflects a changing relationship between inputs and outcomes.",
                "tags": ["drift", "monitoring", "diagnostics"],
            },
            {
                "difficulty": "hard",
                "style": "debugging",
                "question": "A rollback restores the previous model weights, but error rates remain high because the online feature table kept the new schema. What is the real lesson?",
                "options": [
                    "Rollback must cover the full serving contract, including feature schemas and upstream dependencies, not just the model binary.",
                    "Schema changes affect only offline training, so rollback failures after deployment are usually coincidence.",
                    "Once weights are reverted, serving errors must come from traffic spikes rather than data-interface mismatches.",
                    "Feature-table schemas should be changed independently of model versions to simplify operational ownership.",
                ],
                "correct_answer": "Rollback must cover the full serving contract, including feature schemas and upstream dependencies, not just the model binary.",
                "tags": ["rollback", "feature-schema", "incident-response"],
            },
            {
                "difficulty": "hard",
                "style": "scenario",
                "question": "A medical-triage model passed offline evaluation, but the organization still wants production evidence before exposing real users. Which rollout sequence is most defensible?",
                "options": [
                    "Start with shadow evaluation, then use a tightly monitored canary only after the offline and shadow behavior are aligned on safety-critical slices.",
                    "Move directly to a broad canary because shadow deployments cannot reveal any useful production failure mode.",
                    "Launch globally with human override because medical workflows already contain manual review steps.",
                    "Delay monitoring until after launch because safety-critical models require stable traffic before collecting alerts.",
                ],
                "correct_answer": "Start with shadow evaluation, then use a tightly monitored canary only after the offline and shadow behavior are aligned on safety-critical slices.",
                "tags": ["shadow", "canary", "safety-critical"],
            },
            {
                "difficulty": "hard",
                "style": "operations",
                "question": "A customer-support classifier meets latency SLA, but segment-level recall on urgent tickets degrades for two days before anyone notices. What monitoring gap is most obvious?",
                "options": [
                    "The system tracked platform health but lacked task-quality monitoring by critical business segment, so harmful drift stayed invisible.",
                    "Urgent-ticket recall cannot be monitored online because labels are delayed in every support workflow.",
                    "Latency compliance is usually enough because quality issues eventually show up as infrastructure alarms.",
                    "The issue proves alert thresholds should be removed so engineers can inspect dashboards manually instead.",
                ],
                "correct_answer": "The system tracked platform health but lacked task-quality monitoring by critical business segment, so harmful drift stayed invisible.",
                "tags": ["monitoring", "segment-alerts", "incident-detection"],
            },
        ],
    },
]


def clean_text(value):
    return str(value or "").replace("\u2013", "-").replace("\u2014", "-").strip()


def rebalance_options(question):
    options = list(question["options"])
    correct = question["correct_answer"]
    correct_index = options.index(correct)
    while True:
        lengths = [len(option) for option in options]
        longest = max(lengths)
        shortest = min(lengths)
        if lengths.count(longest) == 1 and lengths[correct_index] == longest:
            candidate_indices = [idx for idx in range(len(options)) if idx != correct_index]
            target_idx = min(candidate_indices, key=lambda idx: lengths[idx])
            options[target_idx] = options[target_idx] + " for that pipeline"
            continue
        if lengths.count(shortest) == 1 and lengths[correct_index] == shortest:
            options[correct_index] = options[correct_index] + " in that system"
            correct = options[correct_index]
            correct_index = options.index(correct)
            continue
        break
    question["options"] = options
    question["correct_answer"] = correct
    return question


def build_questions():
    questions = []
    question_index = 1
    for section in SECTIONS:
        topic = section["topic"]
        versions = list(section.get("versions") or DEFAULT_VERSIONS)
        for item in section["items"]:
            question = {
                "id": f"aiml-l3-{question_index:03d}",
                "question": clean_text(item["question"]),
                "options": [clean_text(option) for option in item["options"]],
                "correct_answer": clean_text(item["correct_answer"]),
                "topic": topic,
                "difficulty": item["difficulty"],
                "style": item["style"],
                "tags": list(item["tags"]),
                "role_target": "python_ai_ml",
                "round_target": "L3",
                "version_scope": list(item.get("version_scope") or versions),
            }
            questions.append(rebalance_options(question))
            question_index += 1
    return questions


def write_bank(questions):
    path = DATA_DIR / BANK_KEY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(questions, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main():
    questions = build_questions()
    if len(questions) != 100:
        raise ValueError(f"{BANK_KEY} requires 100 questions, found {len(questions)}")
    validate_question_bank(questions, source_name=BANK_KEY, strict=True)
    write_bank(questions)
    print(f"Wrote {BANK_KEY} with {len(questions)} questions")


if __name__ == "__main__":
    main()
