import json
import re
from copy import deepcopy
from pathlib import Path

from app.services.question_bank.helpers import normalize_text
from app.services.question_bank.java_bank_config import JAVA_BANK_POLICIES
from app.services.question_bank.validator import validate_question_bank

DATA_DIR = Path("app/services/question_bank/data")


def load_bank(relative_path):
    payload = json.loads((DATA_DIR / relative_path).read_text(encoding="utf-8"))
    return payload["questions"] if isinstance(payload, dict) else payload


def clean_text(value):
    return str(value or "").replace("\u2013", "-").replace("\u2014", "-").strip()


SHARED_SENIOR_SOURCE_BLOCKLIST = (
    r"\bapi tests?\b",
    r"\bapi testing\b",
    r"\bhttp client\b",
    r"\bhttp request\b",
    r"\baws\b",
    r"lambda function",
    r"cloudwatch",
    r"\biam\b",
    r"\bsts\b",
    r"eventbridge",
    r"\bsqs\b",
    r"\bsns\b",
    r"spring boot",
    r"actuator",
    r"selenium",
    r"webdriver",
    r"testng",
    r"junit",
    r"rest assured",
)


def sanitize_shared_senior_text(value):
    text = clean_text(value)
    replacements = (
        (r"\bA QA engineer\b", "An engineer"),
        (r"\bA QA automation test\b", "A Java code path"),
        (r"\bA QA automation scenario\b", "A Java service scenario"),
        (r"\bA QA test case\b", "A Java code review"),
        (r"\bA QA test\b", "A Java review"),
        (r"\bDuring a QA test\b", "During execution"),
        (r"\bDuring QA testing\b", "During execution"),
        (r"\bIn a QA test\b", "In a Java review"),
        (r"\bIn a test automation scenario\b", "In a Java service scenario"),
        (r"\bIn a performance test\b", "In a performance review"),
        (r"\bperformance test\b", "performance review"),
        (r"\btest automation\b", "Java service"),
        (r"\btest case\b", "code review"),
        (r"\bIn a test\b", "In a Java code path"),
        (r"\bDuring a test\b", "During execution"),
        (r"\bQA automation\b", "Java"),
        (r"\bQA test\b", "Java review"),
        (r"\bQA\b", "Java"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clone_supplement(question, question_text=None, topic=None, tags=None):
    cloned = deepcopy(question)
    if question_text is not None:
        cloned["question"] = clean_text(question_text)
    if topic is not None:
        cloned["topic"] = topic
    if tags is not None:
        cloned["tags"] = list(tags)
    return cloned


def make_supplement(question, options, correct_answer, topic, tags, versions, score, debug_score, base_style):
    return {
        "question": clean_text(question),
        "options": [clean_text(option) for option in options],
        "correct_answer": clean_text(correct_answer),
        "topic": topic,
        "tags": list(tags),
        "version_scope": list(versions),
        "difficulty_score": int(score),
        "debug_score": int(debug_score),
        "base_style": base_style,
        "source_kind": "supplement",
    }


def rebalance_options(question):
    options = list(question["options"])
    correct = question["correct_answer"]
    lengths = [len(option) for option in options]
    correct_index = options.index(correct)
    while True:
        lengths = [len(option) for option in options]
        longest = max(lengths)
        shortest = min(lengths)
        if lengths.count(longest) == 1 and lengths[correct_index] == longest:
            candidate_indices = [idx for idx in range(len(options)) if idx != correct_index]
            target_idx = min(candidate_indices, key=lambda idx: lengths[idx])
            options[target_idx] = options[target_idx] + " for that production scenario"
            continue
        if lengths.count(shortest) == 1 and lengths[correct_index] == shortest:
            options[correct_index] = options[correct_index] + " in that implementation"
            correct = options[correct_index]
            continue
        break
    question["options"] = options
    question["correct_answer"] = correct
    return question


def keyword_tags(question_text, extra_tags=None):
    text = normalize_text(question_text)
    tags = set(extra_tags or [])
    keyword_map = {
        "stream": "streams",
        "lambda": "lambdas",
        "optional": "optional",
        "hashmap": "hashmap",
        "hashcode": "hashcode",
        "equals": "equals-hashcode",
        "thread": "threads",
        "executor": "executors",
        "future": "future",
        "junit": "junit",
        "testng": "testng",
        "selenium": "selenium",
        "webdriver": "webdriver",
        "rest assured": "rest-assured",
        "api": "api-testing",
        "lambda function": "lambda-runtime",
        "snapstart": "snapstart",
        "credentials": "credentials",
        "assumerole": "sts",
        "actuator": "actuator",
        "cloudwatch": "observability",
        "x-ray": "tracing",
        "virtual thread": "virtual-threads",
        "gc": "gc",
        "heap": "heap",
        "spring": "spring-boot",
    }
    for marker, tag in keyword_map.items():
        if marker in text:
            tags.add(tag)
    return sorted(tags or {"java"})


def old_topic_map(bank_key, source_topic, question_text):
    text = normalize_text(question_text)
    if bank_key == "java/java_senior_theory_debug.json":
        if any(
            marker in text
            for marker in (
                "root cause",
                "fails to compile",
                "compilation error",
                "deadlock",
                "race condition",
                "stack trace",
                "stuck",
                "debug",
                "investigate",
                "diagnose",
                "bug",
            )
        ):
            return "Practical Debugging"
        if source_topic == "JVM Internals & Memory Management" or any(
            marker in text for marker in ("heap", "garbage collector", "garbage collection", "gc", "memory leak")
        ):
            return "JVM Memory and GC"
        if source_topic == "Multi-Threading & Concurrency" or any(
            marker in text for marker in ("thread", "executor", "future", "synchronized", "lock", "volatile")
        ):
            return "Concurrency and Executors"
        if source_topic == "Generics":
            return "Generics and Type Safety"
        if source_topic == "Collections" or any(
            marker in text for marker in ("hashmap", "hashset", "arraylist", "map", "set", "collection", "iterator")
        ):
            return "Collections and Contracts"
        if source_topic in {"Exception Handling", "File I/O"} or any(
            marker in text for marker in ("exception", "try-with-resources", "autocloseable", "reader", "writer")
        ):
            return "Exceptions and Resource Handling"
        if source_topic == "Java 8+ Features" or any(
            marker in text for marker in ("stream", "lambda", "optional", "collector", "method reference", "::")
        ):
            return "Streams Lambdas and Method References"
        if any(marker in text for marker in ("string", "stringbuilder", "stringbuffer", "charsequence")):
            return "Strings and Immutability"
        return "Java Language and Type System"

    if bank_key == "java/java_entry_theory.json":
        if "string" in text or "stringbuilder" in text or "stringbuffer" in text:
            return "Strings and Immutability"
        if "::" in question_text or "method reference" in text:
            return "Methods and References"
        if "stream" in text or "lambda" in text or "optional" in text:
            return "Lambdas and Streams"
        if source_topic == "Exception Handling":
            return "Exceptions"
        if source_topic == "Collections":
            return "Collections Basics"
        return "Java Language Fundamentals"

    if bank_key == "java/java_entry_fundamentals.json":
        if source_topic == "Collections":
            return "Collections Contracts"
        if source_topic == "Generics":
            return "Generics and Type Safety"
        if source_topic == "File I/O":
            return "NIO and Files"
        if source_topic == "Multi-Threading & Concurrency":
            if "executor" in text or "future" in text:
                return "Executor Patterns"
            return "Concurrency Basics"
        if source_topic == "Exception Handling":
            return "Debugging Fundamentals"
        return "Test Utility Design"

    if bank_key == "java/java_qa_core.json":
        if source_topic == "Collections":
            return "Collections Contracts"
        if "retry" in text or source_topic == "Exception Handling":
            return "Exceptions and Retries"
        if "stream" in text or "collector" in text or "optional" in text:
            return "Streams in Test Data"
        if "parallel" in text or "thread" in text or "executor" in text:
            return "Parallel Test Execution"
        if "json" in text or "rest assured" in text or "payload" in text or "api" in text:
            return "JSON and HTTP Clients"
        if "framework" in text or "page object" in text:
            return "Automation Design"
        return "Debugging Automation Utilities"

    if bank_key == "qa/java_qa_advanced.json":
        if "junit" in text:
            return "JUnit Jupiter"
        if "testng" in text:
            return "TestNG Execution"
        if "rest assured" in text:
            return "REST Assured"
        if "wait" in text or "stale" in text or "synchron" in text:
            return "FluentWait and Synchronization"
        if "selenium" in text or "webdriver" in text:
            return "Selenium WebDriver"
        if "ci" in text or "pipeline" in text or "flaky" in text or "artifact" in text:
            return "CI Failure Triage"
        return "Framework Architecture"

    if bank_key == "java/java_aws_advanced.json":
        if source_topic == "Collections":
            return "Collections Contracts"
        if source_topic == "Multi-Threading & Concurrency":
            return "Concurrency and Executors"
        if source_topic == "JVM Internals & Memory Management":
            return "JVM Memory and GC"
        if "retry" in text or "fallback" in text or "backoff" in text:
            return "Resilience Patterns"
        if "exception" in text or "deadlock" in text or "bug" in text:
            return "Backend Debugging"
        return "Spring Boot Architecture"

    if bank_key == "cloud/java_aws_cloud.json":
        if "actuator" in text or "management.endpoints" in text:
            return "Actuator and Management Security"
        if "credential" in text or "defaultcredentialsprovider" in text or "profile" in text:
            return "AWS SDK v2 Credentials"
        if "assumerole" in text or "sts" in text or "trust policy" in text:
            return "IAM and STS"
        if "snapstart" in text or "lambda" in text:
            return "Lambda and SnapStart"
        if "cloudwatch" in text or "x-ray" in text or "trace" in text or "metric" in text:
            return "Observability"
        if "timeout" in text or "latency" in text or "retry" in text or "duplicate" in text:
            return "Cloud Runtime Debugging"
        return "Spring Boot Production Readiness"

    raise ValueError(f"Unsupported bank key: {bank_key}")


def score_old_question(bank_key, question):
    text = normalize_text(question["question"])
    source_topic = question.get("topic", "")
    score = 2
    debug_score = 0
    base_style = "scenario"

    if any(marker in text for marker in ("production", "incident", "latency", "timeout", "flaky", "throttl")):
        score += 5
        debug_score += 6
        base_style = "operations"
    if any(marker in text for marker in ("exception", "deadlock", "stale", "root cause", "retry", "debug")):
        score += 4
        debug_score += 5
    if any(marker in text for marker in ("parallel", "concurrent", "executor", "future", "lambda", "stream")):
        score += 3
    if any(marker in text for marker in ("architecture", "design", "framework", "policy", "security")):
        score += 2
        base_style = "architecture"
    if source_topic in {"JVM Internals & Memory Management", "Multi-Threading & Concurrency"}:
        score += 3
    if source_topic in {"REST Assured", "TestNG Framework", "Selenium WebDriver"}:
        score += 2
    if "what is the output" in text or "what will be the output" in text or "what will be printed" in text:
        score -= 3
    return score, debug_score, base_style


def make_old_candidate(bank_key, role_target, round_target, question):
    question_text = question["question"]
    options = [clean_text(option) for option in question["options"]]
    correct_answer = clean_text(question["correct_answer"])

    if bank_key == "java/java_senior_theory_debug.json":
        question_text = sanitize_shared_senior_text(question_text)
        correct_index = question["options"].index(question["correct_answer"])
        options = [sanitize_shared_senior_text(option) for option in question["options"]]
        correct_answer = clean_text(options[correct_index])

    candidate_question = dict(question)
    candidate_question["question"] = question_text
    score, debug_score, base_style = score_old_question(bank_key, candidate_question)
    mapped_topic = old_topic_map(bank_key, question.get("topic", ""), question_text)
    return {
        "question": clean_text(question_text),
        "options": options,
        "correct_answer": correct_answer,
        "topic": mapped_topic,
        "tags": keyword_tags(question_text),
        "version_scope": ["java17", "java21"],
        "difficulty_score": score,
        "debug_score": debug_score,
        "base_style": base_style,
        "role_target": role_target,
        "round_target": round_target,
        "source_kind": "legacy",
    }


def build_old_pool(bank_key, role_target, round_target):
    if bank_key == "java/java_entry_theory.json":
        source = load_bank("java/java_theory.json")
        return [
            make_old_candidate(bank_key, role_target, round_target, question)
            for question in source
            if question.get("topic") not in {"JVM Internals & Memory Management", "Generics", "File I/O", "Annotations"}
        ]
    if bank_key == "java/java_entry_fundamentals.json":
        source = load_bank("java/java_theory.json")
        return [make_old_candidate(bank_key, role_target, round_target, question) for question in source]
    if bank_key == "java/java_senior_theory_debug.json":
        source = load_bank("java/java_theory.json")
        pool = []
        for question in source:
            text = normalize_text(question["question"])
            if any(re.search(pattern, text, re.IGNORECASE) for pattern in SHARED_SENIOR_SOURCE_BLOCKLIST):
                continue
            pool.append(make_old_candidate(bank_key, role_target, round_target, question))
        return pool
    if bank_key == "java/java_qa_core.json":
        java_pool = [make_old_candidate(bank_key, role_target, round_target, question) for question in load_bank("java/java_theory.json")]
        qa_source = load_bank("qa/qa.json")
        qa_pool = []
        for question in qa_source:
            text = normalize_text(question["question"])
            if any(marker in text for marker in ("parallel", "retry", "payload", "json", "framework", "api", "rest assured")):
                qa_pool.append(make_old_candidate(bank_key, role_target, round_target, question))
        return java_pool + qa_pool
    if bank_key == "qa/java_qa_advanced.json":
        qa_source = load_bank("qa/qa.json")
        return [make_old_candidate(bank_key, role_target, round_target, question) for question in qa_source]
    if bank_key == "java/java_aws_advanced.json":
        source = load_bank("java/java_theory.json")
        return [make_old_candidate(bank_key, role_target, round_target, question) for question in source]
    if bank_key == "cloud/java_aws_cloud.json":
        source = load_bank("cloud/aws_basics.json")
        return [make_old_candidate(bank_key, role_target, round_target, question) for question in source]
    raise ValueError(f"Unsupported bank key: {bank_key}")


def _question_signature(question_text):
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(question_text)).strip()


def select_old_questions(candidates, needed_count):
    selected = []
    seen = set()
    ordered = sorted(candidates, key=lambda item: (item["difficulty_score"], item["debug_score"], len(item["question"])), reverse=True)
    for candidate in ordered:
        signature = _question_signature(candidate["question"])
        if signature in seen:
            continue
        seen.add(signature)
        selected.append(deepcopy(candidate))
        if len(selected) == needed_count:
            break
    if len(selected) != needed_count:
        raise ValueError(f"Needed {needed_count} legacy questions, found {len(selected)}")
    return selected


def assign_difficulties(questions, policy):
    sorted_indices = sorted(
        range(len(questions)),
        key=lambda idx: (questions[idx]["difficulty_score"], questions[idx]["debug_score"], len(questions[idx]["question"])),
        reverse=True,
    )
    difficulty_counts = policy["difficulty_counts"]
    hard_cutoff = difficulty_counts["hard"]
    medium_cutoff = hard_cutoff + difficulty_counts["medium"]
    hard_indices = set(sorted_indices[:hard_cutoff])
    medium_indices = set(sorted_indices[hard_cutoff:medium_cutoff])
    for idx, question in enumerate(questions):
        if idx in hard_indices:
            question["difficulty"] = "hard"
        elif idx in medium_indices:
            question["difficulty"] = "medium"
        else:
            question["difficulty"] = "easy"


def assign_styles(questions, policy):
    for difficulty, debug_needed in policy["debugging_counts"].items():
        bucket = [question for question in questions if question["difficulty"] == difficulty]
        ordered = sorted(bucket, key=lambda item: item["debug_score"], reverse=True)
        debug_set = {id(item) for item in ordered[:debug_needed]}
        for question in bucket:
            if id(question) in debug_set:
                question["style"] = "debugging"
            else:
                question["style"] = question["base_style"]


def finalize_questions(bank_key, role_target, round_target, questions):
    policy = JAVA_BANK_POLICIES[bank_key]
    assign_difficulties(questions, policy)
    assign_styles(questions, policy)
    finalized = []
    for idx, question in enumerate(questions, start=1):
        clean_question = {
            "id": f"{role_target.replace('_', '-')}-{round_target.lower()}-{idx:03d}",
            "question": question["question"],
            "options": list(question["options"]),
            "correct_answer": question["correct_answer"],
            "topic": question["topic"],
            "difficulty": question["difficulty"],
            "style": question["style"],
            "tags": sorted(set(question["tags"])),
            "role_target": role_target,
            "round_target": round_target,
            "version_scope": list(question["version_scope"]),
        }
        finalized.append(rebalance_options(clean_question))
    validate_question_bank(finalized, source_name=bank_key, strict=True)
    return finalized


def write_bank(bank_key, questions):
    path = DATA_DIR / bank_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(questions, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


JAVA_ENTRY_THEORY_SUPPLEMENTS = [
    make_supplement(
        "A junior engineer stores customer names in a String and calls name.trim(); before logging, but the log still contains leading spaces. What explains the bug?",
        [
            "String is immutable, so trim() returns a new value that must be assigned back.",
            "trim() changes the String only after the next garbage-collection cycle.",
            "trim() works only on text coming from a BufferedReader.",
            "The JVM skips trim() when the String came from an HTTP request.",
        ],
        "String is immutable, so trim() returns a new value that must be assigned back.",
        "Strings and Immutability",
        ["strings", "immutability"],
        ["java17", "java21"],
        4,
        7,
        "scenario",
    ),
    make_supplement(
        "Which change is the best fit when a service builds an audit line inside a tight loop and currently uses repeated String concatenation?",
        [
            "Use a local StringBuilder and append fragments before converting once at the end.",
            "Keep String concatenation and call System.gc() after every hundred iterations.",
            "Wrap the String in Optional so the JVM can optimize every append.",
            "Mark the String variable final so concatenation happens in place.",
        ],
        "Use a local StringBuilder and append fragments before converting once at the end.",
        "Strings and Immutability",
        ["strings", "stringbuilder", "performance"],
        ["java17", "java21"],
        3,
        2,
        "architecture",
    ),
    make_supplement(
        "A helper method reference fails to compile after a teammate overloads parse() with two signatures. What is the most likely reason?",
        [
            "The target functional interface no longer resolves to one unambiguous overload.",
            "Method references stop working whenever the method becomes static.",
            "Overloaded methods can be used only with lambdas, never with method references.",
            "The compiler rejects method references when return types are boxed.",
        ],
        "The target functional interface no longer resolves to one unambiguous overload.",
        "Methods and References",
        ["method-references", "overloading"],
        ["java17", "java21"],
        5,
        6,
        "scenario",
    ),
    make_supplement(
        "Which review comment is the strongest when a team is replacing x -> service.parse(x) with Service::parse everywhere?",
        [
            "Confirm that the referenced method still matches the functional interface after overloads and generics are applied.",
            "Avoid method references because they always allocate more objects than lambdas.",
            "Prefer anonymous classes because the JIT cannot inline method references.",
            "Require method references only for private methods to avoid reflection overhead.",
        ],
        "Confirm that the referenced method still matches the functional interface after overloads and generics are applied.",
        "Methods and References",
        ["method-references", "functional-interfaces"],
        ["java17", "java21"],
        4,
        1,
        "architecture",
    ),
    make_supplement(
        "A trainee catches Exception around file parsing and logs only e.getMessage();. Later, operations cannot tell whether the failure was validation, I/O, or configuration. What is the main problem?",
        [
            "The broad catch removes useful exception type and stack-context information needed for diagnosis.",
            "The bug happens because checked exceptions can never be logged safely.",
            "The parser should return null on all failures so callers can inspect it.",
            "Logging only the message forces the JVM to wrap every exception twice.",
        ],
        "The broad catch removes useful exception type and stack-context information needed for diagnosis.",
        "Debugging Fundamentals",
        ["exceptions", "logging", "diagnostics"],
        ["java17", "java21"],
        4,
        8,
        "operations",
    ),
]

JAVA_ENTRY_FUNDAMENTALS_SUPPLEMENTS = [
    make_supplement(
        "A cache uses Customer objects as HashMap keys and later updates the email field that equals() and hashCode() depend on. Why do lookups start failing?",
        [
            "Changing a field used in equals() and hashCode() after insertion makes the key unstable in the map.",
            "HashMap disallows mutable values whenever the key type is custom.",
            "The update turns the entry into a weak reference, so the key disappears.",
            "The map silently switches to identity comparison after any field mutation.",
        ],
        "Changing a field used in equals() and hashCode() after insertion makes the key unstable in the map.",
        "Collections Contracts",
        ["hashmap", "equals-hashcode", "immutability"],
        ["java17", "java21"],
        7,
        9,
        "scenario",
    ),
    make_supplement(
        "Which fix best addresses a HashMap bug caused by mutable business keys?",
        [
            "Use immutable key fields or map by a stable surrogate key instead of mutating the existing key object.",
            "Switch to TreeMap because it ignores hashCode() once the first insert succeeds.",
            "Call map.rehash() after every business update so bucket positions refresh.",
            "Mark the map synchronized so mutated keys become visible again.",
        ],
        "Use immutable key fields or map by a stable surrogate key instead of mutating the existing key object.",
        "Collections Contracts",
        ["hashmap", "immutability", "design"],
        ["java17", "java21"],
        6,
        4,
        "architecture",
    ),
    make_supplement(
        "A generic helper accepts List items and later inserts a String into a list that the caller passed as List<Integer>. Where is the design fault?",
        [
            "Using a raw type bypassed compile-time checks and allowed an invalid element to enter the list.",
            "Generics are enforced only at runtime, so the caller must cast each insert.",
            "List<Integer> is covariant, so adding String is legal until iteration starts.",
            "The compiler erases Integer to Object, so all list inserts are equally valid.",
        ],
        "Using a raw type bypassed compile-time checks and allowed an invalid element to enter the list.",
        "Generics and Type Safety",
        ["generics", "raw-types", "type-safety"],
        ["java17", "java21"],
        6,
        8,
        "scenario",
    ),
    make_supplement(
        "Which API shape is safer for a utility that only reads from a list of Number subtypes?",
        [
            "Accept List<? extends Number> so callers can pass Integer, Long, or BigDecimal lists safely for reading.",
            "Accept raw List so every numeric subtype is handled without generic syntax.",
            "Accept List<Object> because every Number list widens automatically to Object.",
            "Accept List<? super Number> because upper-bounded wildcards are only for writing.",
        ],
        "Accept List<? extends Number> so callers can pass Integer, Long, or BigDecimal lists safely for reading.",
        "Generics and Type Safety",
        ["generics", "wildcards", "api-design"],
        ["java17", "java21"],
        5,
        2,
        "architecture",
    ),
    make_supplement(
        "A file-import tool reads a 6 GB CSV with Files.readAllLines(path) and the JVM runs out of memory. What is the most likely reason?",
        [
            "readAllLines loads the complete file into memory, which is a poor fit for very large inputs.",
            "Path objects pin native buffers, so large files always exhaust direct memory first.",
            "The JVM disables streaming I/O when the file extension is .csv.",
            "Files.readAllLines stores every line twice whenever UTF-8 is detected.",
        ],
        "readAllLines loads the complete file into memory, which is a poor fit for very large inputs.",
        "NIO and Files",
        ["nio", "files", "memory"],
        ["java17", "java21"],
        6,
        8,
        "operations",
    ),
    make_supplement(
        "Which refactor is best when a batch reader must process a huge text file without holding all lines in heap memory?",
        [
            "Stream the file with Files.lines or a buffered reader and process records incrementally.",
            "Call readAllLines twice so the second read hits the operating-system cache.",
            "Wrap the file in Optional<Path> so the runtime can free lines eagerly.",
            "Convert the file to a String first and split it on line endings after loading.",
        ],
        "Stream the file with Files.lines or a buffered reader and process records incrementally.",
        "NIO and Files",
        ["nio", "streaming", "performance"],
        ["java17", "java21"],
        5,
        2,
        "operations",
    ),
    make_supplement(
        "A scheduled executor keeps launching work, but the application never shuts down cleanly after tests finish. Which omission is the most likely cause?",
        [
            "The executor was never shut down, so its worker threads keep the JVM alive.",
            "Scheduled executors stop automatically once the last Future is garbage-collected.",
            "Only virtual threads need shutdown(); platform-thread pools exit on their own.",
            "The bug exists because scheduleAtFixedRate must be wrapped in synchronized.",
        ],
        "The executor was never shut down, so its worker threads keep the JVM alive.",
        "Executor Patterns",
        ["executors", "shutdown", "lifecycle"],
        ["java17", "java21"],
        5,
        8,
        "scenario",
    ),
    make_supplement(
        "Which executor choice is safer when an internal tool submits bursty I/O-bound jobs but must avoid unbounded thread growth?",
        [
            "Use a bounded ThreadPoolExecutor so queue size and thread count stay under explicit control.",
            "Use Executors.newCachedThreadPool() because cached pools cap themselves at CPU count.",
            "Create one new Thread per task so each request owns its own lifecycle.",
            "Use parallelStream() for all jobs because it replaces manual backpressure design.",
        ],
        "Use a bounded ThreadPoolExecutor so queue size and thread count stay under explicit control.",
        "Executor Patterns",
        ["executors", "threadpool", "backpressure"],
        ["java17", "java21"],
        7,
        3,
        "architecture",
    ),
]

JAVA_QA_CORE_SUPPLEMENTS = [
    make_supplement(
        "A retry helper around UI actions catches Exception and retries three times, but real assertion failures become harder to diagnose. What is the design flaw?",
        [
            "The helper retries on every exception type instead of only on transient failures the framework expects.",
            "Retries should never be used with Selenium because the driver already retries assertions.",
            "Catching Exception converts all failures into checked exceptions automatically.",
            "Assertion errors are safe to ignore because they are generated by the test framework.",
        ],
        "The helper retries on every exception type instead of only on transient failures the framework expects.",
        "Exceptions and Retries",
        ["retry", "assertions", "automation"],
        ["java17", "java21"],
        6,
        8,
        "scenario",
    ),
    make_supplement(
        "Which retry design is safer for a Java-based automation framework?",
        [
            "Retry only clearly transient operations, keep attempts visible in logs, and stop retrying assertion logic that indicates a true defect.",
            "Retry every failure path globally so flaky and real failures are treated the same way.",
            "Wrap the whole suite in one outer retry loop to maximize pass rate.",
            "Convert assertion failures to warnings so the framework can continue after the retry budget.",
        ],
        "Retry only clearly transient operations, keep attempts visible in logs, and stop retrying assertion logic that indicates a true defect.",
        "Exceptions and Retries",
        ["retry", "framework-design", "logging"],
        ["java17", "java21"],
        6,
        3,
        "architecture",
    ),
    make_supplement(
        "Parallel API tests share a mutable Jackson ObjectMapper configuration and one suite changes deserialization settings mid-run. What is the most likely impact?",
        [
            "Tests can become order-dependent because later requests observe a different shared mapper configuration.",
            "ObjectMapper is immutable once created, so later configuration calls are ignored.",
            "Changing mapper settings affects only the current thread by default.",
            "The JVM clones mapper state automatically whenever tests run in parallel.",
        ],
        "Tests can become order-dependent because later requests observe a different shared mapper configuration.",
        "JSON and HTTP Clients",
        ["json", "objectmapper", "parallel-tests"],
        ["java17", "java21"],
        7,
        9,
        "scenario",
    ),
    make_supplement(
        "A test-data stream sorts users in parallel and appends failures to a shared ArrayList inside forEach. Why is that risky?",
        [
            "The shared mutable list is not safe for parallel writes, so results can be lost or corrupted.",
            "Parallel streams guarantee write ordering only for ArrayList targets, so the list is the correct sink.",
            "ArrayList becomes thread-safe when used inside a stream pipeline.",
            "The stream switches to sequential mode once it detects a mutable collector.",
        ],
        "The shared mutable list is not safe for parallel writes, so results can be lost or corrupted.",
        "Streams in Test Data",
        ["streams", "parallel", "test-data"],
        ["java17", "java21"],
        7,
        8,
        "scenario",
    ),
    make_supplement(
        "Which refactor is best for a Java automation utility that enriches test data in parallel?",
        [
            "Return a collected result with thread-safe collectors instead of mutating shared state from forEach callbacks.",
            "Keep the shared mutable list and add synchronized to every lambda body.",
            "Convert the stream to raw types so the pipeline can skip generic collector checks.",
            "Replace the stream with Thread.sleep between inserts so threads do not overlap.",
        ],
        "Return a collected result with thread-safe collectors instead of mutating shared state from forEach callbacks.",
        "Streams in Test Data",
        ["streams", "collectors", "parallel"],
        ["java17", "java21"],
        6,
        4,
        "architecture",
    ),
]
JAVA_QA_ADVANCED_SUPPLEMENTS = [
    make_supplement(
        "A JUnit 5 test class switches to @TestInstance(PER_CLASS) and now one failing test pollutes another through shared fields. What changed?",
        [
            "JUnit now reuses one test instance, so mutable instance state is shared across test methods.",
            "PER_CLASS creates a fresh test instance for every assertion instead of every method.",
            "JUnit disables @BeforeEach when PER_CLASS is enabled.",
            "PER_CLASS forces all tests to run sequentially in one transaction.",
        ],
        "JUnit now reuses one test instance, so mutable instance state is shared across test methods.",
        "JUnit Jupiter",
        ["junit", "test-lifecycle", "state-leaks"],
        ["java17", "java21"],
        7,
        9,
        "scenario",
    ),
    make_supplement(
        "Which JUnit 5 design is safer when a test class stores mutable fixtures that must not leak between methods?",
        [
            "Keep the default per-method lifecycle or recreate mutable fixtures in @BeforeEach.",
            "Use @TestInstance(PER_CLASS) so JUnit can cache every mutable field for reuse.",
            "Move all mutable state into static fields to make test order deterministic.",
            "Replace @BeforeEach with Thread.sleep so background cleanup finishes first.",
        ],
        "Keep the default per-method lifecycle or recreate mutable fixtures in @BeforeEach.",
        "JUnit Jupiter",
        ["junit", "fixtures", "test-design"],
        ["java17", "java21"],
        6,
        3,
        "architecture",
    ),
    make_supplement(
        "A Selenium wrapper sets a 20-second implicit wait and also uses WebDriverWait with 20 seconds. Why does the suite feel slower and less predictable?",
        [
            "Mixing implicit and explicit waits can multiply polling delays and make timeouts harder to reason about.",
            "WebDriverWait disables implicit waits, so the 20-second setting becomes harmless.",
            "Implicit waits apply only to click() while explicit waits apply only to findElement().",
            "The slowdown happens because Selenium runs both waits on separate threads and merges the result.",
        ],
        "Mixing implicit and explicit waits can multiply polling delays and make timeouts harder to reason about.",
        "FluentWait and Synchronization",
        ["selenium", "waits", "synchronization"],
        ["java17", "java21"],
        7,
        9,
        "operations",
    ),
    make_supplement(
        "A page object caches a WebElement for the checkout button, but React re-renders the DOM before click. What is the most likely failure mode?",
        [
            "The cached element reference becomes stale because the underlying DOM node was replaced.",
            "React prevents Selenium from clicking any element after re-render.",
            "The click fails only when the WebElement was located by CSS instead of XPath.",
            "The JVM clears cached WebElements whenever garbage collection runs.",
        ],
        "The cached element reference becomes stale because the underlying DOM node was replaced.",
        "Selenium WebDriver",
        ["selenium", "stale-element", "page-objects"],
        ["java17", "java21"],
        7,
        8,
        "scenario",
    ),
    make_supplement(
        "A TestNG suite uses parallel=\"methods\" and a static WebDriver field. Why do tests begin stealing focus from each other?",
        [
            "Parallel methods share the same static driver reference, so commands from different tests hit the same browser instance.",
            "Static fields become thread-local automatically when TestNG enables method parallelism.",
            "TestNG clones the browser per method but keeps windows synchronized on purpose.",
            "Method parallelism affects only data providers, not driver usage.",
        ],
        "Parallel methods share the same static driver reference, so commands from different tests hit the same browser instance.",
        "TestNG Execution",
        ["testng", "parallel", "webdriver"],
        ["java17", "java21"],
        7,
        9,
        "scenario",
    ),
    make_supplement(
        "A REST Assured base specification is stored in a mutable static object and different suites override headers in parallel. What risk does that introduce?",
        [
            "Requests become order-dependent because one suite can leak header changes into another suite's calls.",
            "REST Assured snapshots every static specification per thread, so no leakage is possible.",
            "Static RequestSpecification objects are immutable once the first request is sent.",
            "Header overrides are ignored whenever a base URI is also configured.",
        ],
        "Requests become order-dependent because one suite can leak header changes into another suite's calls.",
        "REST Assured",
        ["rest-assured", "parallel", "shared-state"],
        ["java17", "java21"],
        7,
        8,
        "scenario",
    ),
    make_supplement(
        "A CI failure report only stores 'Assertion failed' without request payloads, response bodies, browser logs, or screenshots. What is the main operational problem?",
        [
            "Engineers lose the evidence needed to distinguish product defects, environment issues, and flaky automation.",
            "CI pipelines should avoid artifacts because they slow down future retries.",
            "Screenshots and payloads matter only for manual testing, not automation failures.",
            "The lack of artifacts affects only UI tests and is irrelevant for API suites.",
        ],
        "Engineers lose the evidence needed to distinguish product defects, environment issues, and flaky automation.",
        "CI Failure Triage",
        ["ci", "artifacts", "failure-triage"],
        ["java17", "java21"],
        6,
        8,
        "operations",
    ),
    make_supplement(
        "Which failure-handling change is strongest when a UI suite has become flaky under load on Selenium Grid?",
        [
            "Capture browser logs, network traces, screenshots, and node metadata so recurring failure signatures can be grouped and fixed.",
            "Retry every failed test three times and publish only the final result to keep reports clean.",
            "Disable all explicit waits so timing issues fail faster and look more deterministic.",
            "Run every test on the same node to avoid comparing behavior across browsers.",
        ],
        "Capture browser logs, network traces, screenshots, and node metadata so recurring failure signatures can be grouped and fixed.",
        "CI Failure Triage",
        ["ci", "grid", "observability"],
        ["java17", "java21"],
        6,
        4,
        "operations",
    ),
]

JAVA_AWS_ADVANCED_SUPPLEMENTS = [
    make_supplement(
        "A service moves request handling to virtual threads but still wraps a blocking JDBC call inside synchronized(this). Why can throughput remain poor?",
        [
            "The synchronized block can pin the virtual thread to its carrier while the blocking call runs.",
            "Virtual threads never work with JDBC, even when the driver is modern.",
            "synchronized forces every virtual thread to become a daemon thread.",
            "Carrier threads ignore synchronized blocks and schedule around them automatically.",
        ],
        "The synchronized block can pin the virtual thread to its carrier while the blocking call runs.",
        "Virtual Threads",
        ["virtual-threads", "pinning", "jdbc"],
        ["java21"],
        8,
        9,
        "scenario",
    ),
    make_supplement(
        "Which refactor is most appropriate when a virtual-thread endpoint still serializes around a slow remote call?",
        [
            "Reduce synchronized scope or replace it with finer-grained concurrency control around only truly shared state.",
            "Increase the platform-thread pool so pinned virtual threads become invisible.",
            "Replace the remote call with parallelStream() to bypass carrier-thread scheduling.",
            "Move the synchronized block to a static initializer so it runs only once per JVM.",
        ],
        "Reduce synchronized scope or replace it with finer-grained concurrency control around only truly shared state.",
        "Virtual Threads",
        ["virtual-threads", "locking", "design"],
        ["java21"],
        7,
        4,
        "architecture",
    ),
    make_supplement(
        "A Spring Boot controller catches Exception and still returns HTTP 200 with an error message in the body. Why is that dangerous in production?",
        [
            "Clients, monitors, and retries see a success status and lose the signal that the request actually failed.",
            "Spring Boot rewrites all 200 responses to 500 once Actuator is enabled.",
            "The framework refuses to serialize error bodies unless the status is 4xx.",
            "Returning 200 prevents exceptions from appearing in logs entirely.",
        ],
        "Clients, monitors, and retries see a success status and lose the signal that the request actually failed.",
        "Spring Boot Architecture",
        ["spring-boot", "http-status", "error-handling"],
        ["java17", "java21"],
        7,
        8,
        "scenario",
    ),
    make_supplement(
        "Which design is stronger for a backend service that needs consistent error semantics and observable failure paths?",
        [
            "Use typed exceptions or problem-details style responses and map them centrally instead of returning HTTP 200 for failures.",
            "Return HTTP 200 for all responses and let frontends infer failure from message text.",
            "Catch Throwable at the controller edge and suppress stack traces to reduce noise.",
            "Convert all validation errors to RuntimeException so the JVM can optimize them together.",
        ],
        "Use typed exceptions or problem-details style responses and map them centrally instead of returning HTTP 200 for failures.",
        "Spring Boot Architecture",
        ["spring-boot", "exception-mapping", "api-design"],
        ["java17", "java21"],
        7,
        3,
        "architecture",
    ),
    make_supplement(
        "A service wraps an outbound HTTP call with its own retry loop, while the HTTP client and the circuit-breaker library also retry. What is the main production risk?",
        [
            "Layered retries can amplify load and latency, turning a brief dependency issue into a retry storm.",
            "Multiple retry layers are safe because each one reduces total request volume automatically.",
            "Circuit breakers disable all inner retries by default, so the loops never overlap.",
            "Retries cannot increase latency unless the dependency is CPU-bound.",
        ],
        "Layered retries can amplify load and latency, turning a brief dependency issue into a retry storm.",
        "Resilience Patterns",
        ["retry", "resilience", "latency"],
        ["java17", "java21"],
        8,
        9,
        "operations",
    ),
    make_supplement(
        "What is the strongest remediation when duplicate retry logic exists in several layers of a Java service?",
        [
            "Choose one primary retry policy close to the dependency boundary and make every other layer fail fast or observe only.",
            "Add exponential backoff to each layer independently so the retries cancel each other out.",
            "Increase the thread pool so the service can absorb every retry burst concurrently.",
            "Move retries into finally blocks so cleanup happens before each next attempt.",
        ],
        "Choose one primary retry policy close to the dependency boundary and make every other layer fail fast or observe only.",
        "Resilience Patterns",
        ["retry", "resilience", "design"],
        ["java17", "java21"],
        7,
        4,
        "architecture",
    ),
    make_supplement(
        "Heap usage climbs after every batch import, and a singleton bean keeps all processed rows in a List for 'future troubleshooting'. What is the most likely explanation?",
        [
            "The singleton is retaining objects that should have become unreachable, so the heap keeps growing between runs.",
            "The JVM refuses to collect lists stored inside Spring-managed beans.",
            "GC in Java 17 does not reclaim objects created inside streams.",
            "A singleton bean always stores its fields in native memory instead of heap memory.",
        ],
        "The singleton is retaining objects that should have become unreachable, so the heap keeps growing between runs.",
        "JVM Memory and GC",
        ["heap", "gc", "memory-leak"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "Which review recommendation is best when a batch service stores every processed payload in a singleton cache for convenience?",
        [
            "Retain only bounded summaries or identifiers and let the heavy payloads fall out of scope once processing finishes.",
            "Mark the cache final so the GC can compact it more aggressively.",
            "Replace the List with a LinkedList so heap growth stops after the first expansion.",
            "Call System.gc() at the end of each batch to guarantee reclamation.",
        ],
        "Retain only bounded summaries or identifiers and let the heavy payloads fall out of scope once processing finishes.",
        "JVM Memory and GC",
        ["heap", "gc", "design"],
        ["java17", "java21"],
        6,
        3,
        "architecture",
    ),
    make_supplement(
        "A fixed thread pool accepts blocking tasks faster than they complete, and queue length keeps growing during incidents. What production issue is emerging?",
        [
            "The executor has no effective backpressure, so latency and memory usage rise as work piles up.",
            "A fixed pool automatically scales once the queue crosses the CPU-count threshold.",
            "Blocking tasks are harmless in fixed pools because each worker owns its own queue.",
            "Queue growth matters only for scheduled executors, not standard thread pools.",
        ],
        "The executor has no effective backpressure, so latency and memory usage rise as work piles up.",
        "Concurrency and Executors",
        ["executors", "queues", "backpressure"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "Which executor design is safer when tasks may block on remote dependencies for unpredictable durations?",
        [
            "Use bounded queues, explicit rejection or throttling, and metrics so the service applies backpressure before saturation.",
            "Use an unbounded queue because it prevents task rejection and therefore guarantees stability.",
            "Use a single-thread executor so requests line up fairly and never overload the dependency.",
            "Move blocking work into synchronized blocks so workers do not compete for CPU.",
        ],
        "Use bounded queues, explicit rejection or throttling, and metrics so the service applies backpressure before saturation.",
        "Concurrency and Executors",
        ["executors", "backpressure", "capacity-planning"],
        ["java17", "java21"],
        7,
        3,
        "architecture",
    ),
]
JAVA_AWS_CLOUD_SUPPLEMENTS = [
    make_supplement(
        "A Spring Boot service reports healthy even when its Kafka publisher cannot send messages because the readiness endpoint checks only JVM liveness. What is the gap?",
        [
            "Readiness is not validating a dependency the service needs before it should receive live traffic.",
            "Kafka failures should appear only on the liveness endpoint, never readiness.",
            "Spring Boot forbids dependency checks inside readiness probes.",
            "Traffic routing is unrelated to readiness once the JVM has started.",
        ],
        "Readiness is not validating a dependency the service needs before it should receive live traffic.",
        "Spring Boot Production Readiness",
        ["spring-boot", "readiness", "kafka"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "Which production-readiness improvement is strongest for a Spring Boot service that currently exposes only a ping endpoint?",
        [
            "Separate liveness from readiness and include dependency-aware health signals plus deployment-time observability.",
            "Return HTTP 200 from every health endpoint so load balancers never drain traffic.",
            "Disable health groups and rely on thread dumps whenever the service degrades.",
            "Expose heap usage only in logs because health endpoints should never mention dependencies.",
        ],
        "Separate liveness from readiness and include dependency-aware health signals plus deployment-time observability.",
        "Spring Boot Production Readiness",
        ["spring-boot", "health", "operations"],
        ["java17", "java21"],
        6,
        3,
        "operations",
    ),
    make_supplement(
        "A Boot API starts accepting traffic before Flyway migrations complete, causing random SQL failures during rollout. What is the main release-risk?",
        [
            "The instance becomes ready before its schema state is actually safe for production traffic.",
            "Flyway always blocks the network port until every migration finishes.",
            "SQL failures during startup are harmless because the first request retries them automatically.",
            "Schema drift can occur only when blue-green deployment is disabled.",
        ],
        "The instance becomes ready before its schema state is actually safe for production traffic.",
        "Spring Boot Production Readiness",
        ["spring-boot", "database", "deployments"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "Which deployment design is safer when a Boot service depends on migrations, warm caches, and message subscriptions before taking live traffic?",
        [
            "Delay readiness until startup tasks complete and the instance can serve real requests without predictable failure.",
            "Mark the instance live and ready as soon as the JVM opens the HTTP port.",
            "Disable readiness probes because startup dependencies slow down scale-out.",
            "Use only liveness probes and let the load balancer discover failures by retry volume.",
        ],
        "Delay readiness until startup tasks complete and the instance can serve real requests without predictable failure.",
        "Spring Boot Production Readiness",
        ["spring-boot", "deployments", "readiness"],
        ["java17", "java21"],
        6,
        3,
        "architecture",
    ),
    make_supplement(
        "A service ships without request IDs in logs, metrics, or traces. During an incident, teams cannot follow one order across services. What is missing?",
        [
            "The service lacks correlated observability, so one business request cannot be stitched across telemetry signals.",
            "Distributed systems require only logs; metrics and traces are optional duplicates.",
            "Correlation IDs are needed only for asynchronous systems, not HTTP APIs.",
            "CloudWatch creates request IDs automatically for every custom log line.",
        ],
        "The service lacks correlated observability, so one business request cannot be stitched across telemetry signals.",
        "Spring Boot Production Readiness",
        ["spring-boot", "observability", "correlation"],
        ["java17", "java21"],
        7,
        7,
        "operations",
    ),
    make_supplement(
        "An internal team enables every Actuator endpoint on the public ingress because it is 'only for non-prod'. Which risk should be flagged first?",
        [
            "Operational endpoints can leak configuration, environment, or diagnostic data that should stay behind trusted boundaries.",
            "Actuator endpoints are safe in public because they return JSON instead of HTML.",
            "Only /health is sensitive; every other Actuator endpoint is read-only and harmless.",
            "Actuator exposure matters only when the application does not use TLS.",
        ],
        "Operational endpoints can leak configuration, environment, or diagnostic data that should stay behind trusted boundaries.",
        "Actuator and Management Security",
        ["actuator", "security", "ingress"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "Which Actuator exposure pattern is safer for production?",
        [
            "Expose only the minimum endpoints needed, keep sensitive ones on a protected management plane, and enforce authentication.",
            "Expose every endpoint so SREs can troubleshoot without changing configuration during incidents.",
            "Expose /env publicly because it helps clients self-diagnose request problems.",
            "Expose /heapdump publicly but rate-limit it to once per minute.",
        ],
        "Expose only the minimum endpoints needed, keep sensitive ones on a protected management plane, and enforce authentication.",
        "Actuator and Management Security",
        ["actuator", "least-privilege", "security"],
        ["java17", "java21"],
        6,
        3,
        "architecture",
    ),
    make_supplement(
        "A production incident requires heap analysis, but the service exposes /heapdump on the same public gateway as the customer API. Why is that dangerous?",
        [
            "A heap dump can contain secrets and user data, and exposing it publicly creates an unnecessary high-impact attack path.",
            "Heap dumps are safe to expose because only Java tooling can read them.",
            "The endpoint is harmless as long as the response body is compressed.",
            "Only /threaddump is sensitive; /heapdump contains structure but no actual data.",
        ],
        "A heap dump can contain secrets and user data, and exposing it publicly creates an unnecessary high-impact attack path.",
        "Actuator and Management Security",
        ["actuator", "heapdump", "security"],
        ["java17", "java21"],
        8,
        9,
        "operations",
    ),
    make_supplement(
        "A team wants to expose /prometheus and /health publicly while keeping all other management endpoints internal. What is the key design principle?",
        [
            "Management exposure should be deliberately segmented so monitoring gets what it needs without broadening diagnostic attack surface.",
            "Public exposure is acceptable only if every endpoint returns less than 1 KB of JSON.",
            "Prometheus scraping requires every Actuator endpoint to share one public base path.",
            "Internal endpoints become safe once /health is also public.",
        ],
        "Management exposure should be deliberately segmented so monitoring gets what it needs without broadening diagnostic attack surface.",
        "Actuator and Management Security",
        ["actuator", "prometheus", "security"],
        ["java17", "java21"],
        6,
        4,
        "architecture",
    ),
    make_supplement(
        "A misconfigured reverse proxy exposes /env and /configprops. During incident review, why is this treated as a security bug and not just an ops mistake?",
        [
            "Those endpoints can reveal secrets, internal topology, and configuration assumptions that materially increase attacker leverage.",
            "The problem is cosmetic because Actuator redacts every sensitive key by default in all cases.",
            "Configuration endpoints are safe if the service also exposes a health check.",
            "Reverse proxies strip sensitive Actuator payloads before clients can read them.",
        ],
        "Those endpoints can reveal secrets, internal topology, and configuration assumptions that materially increase attacker leverage.",
        "Actuator and Management Security",
        ["actuator", "config", "security"],
        ["java17", "java21"],
        8,
        8,
        "operations",
    ),
    make_supplement(
        "A Java service runs fine on a developer laptop because the AWS profile is configured locally, but it fails in ECS with 'Unable to load credentials'. What is the most likely cause?",
        [
            "The runtime does not have a valid task role or other provider in the default credentials chain available in that environment.",
            "DefaultCredentialsProvider reads credentials only from ~/.aws even inside ECS.",
            "ECS injects credentials only for Python and Node runtimes, not Java.",
            "The AWS SDK v2 requires static keys whenever the service runs inside containers.",
        ],
        "The runtime does not have a valid task role or other provider in the default credentials chain available in that environment.",
        "AWS SDK v2 Credentials",
        ["aws-sdk-v2", "credentials", "ecs"],
        ["java17", "java21"],
        7,
        8,
        "scenario",
    ),
    make_supplement(
        "Which credential strategy is preferred for a Java service on ECS or EC2?",
        [
            "Use the default credentials chain with a task role or instance profile instead of baking static keys into configuration.",
            "Store long-lived access keys in application.yml so every environment behaves the same way.",
            "Pass credentials through system properties only, because the SDK ignores role-based providers by default.",
            "Create one IAM user per microservice instance and rotate the passwords weekly.",
        ],
        "Use the default credentials chain with a task role or instance profile instead of baking static keys into configuration.",
        "AWS SDK v2 Credentials",
        ["aws-sdk-v2", "credentials", "iam-roles"],
        ["java17", "java21"],
        6,
        3,
        "architecture",
    ),
    make_supplement(
        "A service accidentally sets AWS_ACCESS_KEY_ID in the container image and also assigns an ECS task role. Why can that be dangerous?",
        [
            "Environment variables can override the role-based path, causing the service to use the wrong credentials everywhere the image runs.",
            "The SDK always merges both providers into one stronger credential set.",
            "Task roles take precedence over every other provider, so the environment variable is ignored safely.",
            "The service will fail to start because the SDK forbids multiple credential sources.",
        ],
        "Environment variables can override the role-based path, causing the service to use the wrong credentials everywhere the image runs.",
        "AWS SDK v2 Credentials",
        ["aws-sdk-v2", "credentials", "containers"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "A deployment role in account A cannot assume a target role in account B even though the caller policy allows sts:AssumeRole. What is the most likely missing piece?",
        [
            "The target role trust policy does not trust the caller principal from account A.",
            "AssumeRole works with caller permissions only; trust policies are optional for cross-account use.",
            "The SDK requires both roles to exist in the same region.",
            "Cross-account AssumeRole fails unless the source role also has s3:ListBucket.",
        ],
        "The target role trust policy does not trust the caller principal from account A.",
        "IAM and STS",
        ["iam", "sts", "assumerole"],
        ["java17", "java21"],
        7,
        8,
        "scenario",
    ),
    make_supplement(
        "Which IAM design is most appropriate when one workload in account A must deploy into account B?",
        [
            "Create a role in account B with a narrow permission set and a trust policy that explicitly allows the source principal in account A.",
            "Share one IAM user and long-lived secret across both accounts to reduce role complexity.",
            "Attach AdministratorAccess to the source role so cross-account API calls inherit all rights automatically.",
            "Copy the target account's root credentials into AWS Secrets Manager and load them at runtime.",
        ],
        "Create a role in account B with a narrow permission set and a trust policy that explicitly allows the source principal in account A.",
        "IAM and STS",
        ["iam", "sts", "least-privilege"],
        ["java17", "java21"],
        6,
        3,
        "architecture",
    ),
    make_supplement(
        "A batch job assumes a role successfully at startup, then begins failing three hours later with expired-token errors. What is the most likely issue?",
        [
            "The workload is holding temporary STS credentials too long instead of refreshing them through the provider chain.",
            "STS credentials never expire once the first API call succeeds.",
            "The AWS SDK v2 refreshes temporary credentials only for Lambda, not long-running services.",
            "Role sessions expire only when the JVM restarts and loses its system properties.",
        ],
        "The workload is holding temporary STS credentials too long instead of refreshing them through the provider chain.",
        "IAM and STS",
        ["sts", "temporary-credentials", "refresh"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "A Java 21 service in EKS uses IRSA, but engineers keep debugging ~/.aws/credentials inside the container. What should they focus on first?",
        [
            "Verify that the pod service account is correctly bound to the IAM role and that the web-identity provider path is available to the SDK.",
            "Copy a personal developer profile into the image so the SDK has a guaranteed local fallback.",
            "Disable IRSA because the Java SDK v2 does not support web-identity credentials.",
            "Switch the service to long-lived IAM user keys because Kubernetes hides all role-based credentials.",
        ],
        "Verify that the pod service account is correctly bound to the IAM role and that the web-identity provider path is available to the SDK.",
        "AWS SDK v2 Credentials",
        ["aws-sdk-v2", "irsa", "web-identity"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "A team hard-codes Region.US_EAST_1 in one SDK client while the rest of the platform runs in eu-west-1. What production risk does that create?",
        [
            "The service can read or write the wrong regional resources even when credentials are otherwise valid.",
            "The SDK automatically rewrites hard-coded regions to the ECS cluster region at runtime.",
            "Regional mismatches affect only S3 and have no impact on other AWS services.",
            "The client falls back to the instance metadata region whenever a static region is wrong.",
        ],
        "The service can read or write the wrong regional resources even when credentials are otherwise valid.",
        "AWS SDK v2 Credentials",
        ["aws-sdk-v2", "region", "configuration"],
        ["java17", "java21"],
        6,
        7,
        "operations",
    ),
    make_supplement(
        "A Java Lambda uses SnapStart and loads an OAuth token into a static field during initialization. Hours later, restored invocations fail authentication. Why?",
        [
            "SnapStart can restore the pre-initialized memory image, so short-lived secrets captured at init can be stale after restore.",
            "SnapStart disables all static fields and reloads them before each invocation.",
            "OAuth tokens become invalid only when Lambda concurrency exceeds one.",
            "Static fields are safe with SnapStart as long as they were created before the first request.",
        ],
        "SnapStart can restore the pre-initialized memory image, so short-lived secrets captured at init can be stale after restore.",
        "Lambda and SnapStart",
        ["lambda", "snapstart", "secrets"],
        ["java17", "java21"],
        8,
        9,
        "operations",
    ),
    make_supplement(
        "Which initialization pattern is safer for Java Lambda functions using SnapStart?",
        [
            "Cache only data that stays valid across restore and refresh volatile secrets or tokens after the function resumes.",
            "Move every secret into a static field so SnapStart never has to retrieve it again.",
            "Disable environment variables because SnapStart restores them incorrectly.",
            "Load every dependency lazily inside the handler and avoid any initialization outside it.",
        ],
        "Cache only data that stays valid across restore and refresh volatile secrets or tokens after the function resumes.",
        "Lambda and SnapStart",
        ["lambda", "snapstart", "initialization"],
        ["java17", "java21"],
        7,
        4,
        "architecture",
    ),
    make_supplement(
        "A Lambda behind API Gateway returns 504s during traffic spikes, but the function logs often show only cold-start dominated invocations. What should engineers investigate first?",
        [
            "The end-to-end path may be spending its budget in cold starts, init work, or downstream calls before API Gateway's timeout is reached.",
            "API Gateway never times out Lambda integrations unless the function crashes.",
            "The 504 proves the Lambda handler returned an invalid JSON body, not a latency issue.",
            "Cold starts matter only for Python and Node runtimes, not Java.",
        ],
        "The end-to-end path may be spending its budget in cold starts, init work, or downstream calls before API Gateway's timeout is reached.",
        "Lambda and SnapStart",
        ["lambda", "api-gateway", "timeouts"],
        ["java17", "java21"],
        8,
        9,
        "operations",
    ),
    make_supplement(
        "A Java Lambda processes duplicate S3 events and writes duplicate rows to DynamoDB. What is the most robust explanation?",
        [
            "The event source and Lambda execution model are at-least-once, so the function needs idempotency instead of assuming one delivery.",
            "DynamoDB duplicates rows automatically whenever a Lambda uses the Java runtime.",
            "S3 guarantees exactly-once delivery, so duplicates prove the SDK retried the PutItem call twice.",
            "Duplicate S3 events occur only when the bucket uses multipart uploads.",
        ],
        "The event source and Lambda execution model are at-least-once, so the function needs idempotency instead of assuming one delivery.",
        "Lambda and SnapStart",
        ["lambda", "idempotency", "s3-events"],
        ["java17", "java21"],
        7,
        8,
        "scenario",
    ),
    make_supplement(
        "Which Java Lambda design is safest for webhook processing under retries and duplicate deliveries?",
        [
            "Persist an idempotency key or event identifier before side effects so repeated deliveries can be detected and skipped safely.",
            "Increase the function timeout so retries stop happening.",
            "Use a static Set in memory to remember every processed event forever.",
            "Write side effects first and store the idempotency key only after success to avoid extra reads.",
        ],
        "Persist an idempotency key or event identifier before side effects so repeated deliveries can be detected and skipped safely.",
        "Lambda and SnapStart",
        ["lambda", "idempotency", "webhooks"],
        ["java17", "java21"],
        7,
        4,
        "architecture",
    ),
    make_supplement(
        "A service emits request logs and custom metrics, but neither includes the order ID or trace ID. What is the main observability loss?",
        [
            "Teams cannot correlate symptoms across signals for one business request, which slows root-cause isolation.",
            "CloudWatch rejects metrics unless every log line repeats the same identifier.",
            "Tracing IDs are useful only for front-end telemetry, not backend services.",
            "Metrics become invalid whenever logs omit the same business field.",
        ],
        "Teams cannot correlate symptoms across signals for one business request, which slows root-cause isolation.",
        "Observability",
        ["observability", "correlation", "metrics"],
        ["java17", "java21"],
        6,
        8,
        "operations",
    ),
    make_supplement(
        "Which instrumentation change best improves a Java microservice platform's ability to debug cross-service latency?",
        [
            "Propagate trace context and consistent request IDs through logs, metrics, and downstream calls instead of instrumenting each signal in isolation.",
            "Increase log volume so more stack traces are captured without changing any identifiers.",
            "Store every request body in metrics because cardinality does not affect observability cost.",
            "Disable sampling entirely and keep only access logs to simplify dashboards.",
        ],
        "Propagate trace context and consistent request IDs through logs, metrics, and downstream calls instead of instrumenting each signal in isolation.",
        "Observability",
        ["observability", "tracing", "correlation"],
        ["java17", "java21"],
        7,
        4,
        "architecture",
    ),
    make_supplement(
        "An alarm fires on p95 latency, but the dashboard shows no breakdown by dependency, region, or response code. What is the operational weakness?",
        [
            "The telemetry cannot narrow the symptom to a failing path, so engineers have alerting without actionable diagnosis.",
            "Latency alarms should never be paired with dashboards because alerts must remain generic.",
            "Response-code dimensions are useful only for synchronous systems, not cloud APIs.",
            "CloudWatch metrics lose accuracy once more than one dimension is published.",
        ],
        "The telemetry cannot narrow the symptom to a failing path, so engineers have alerting without actionable diagnosis.",
        "Observability",
        ["observability", "latency", "dashboards"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "A platform enables tracing at the API layer but never propagates the context into downstream Kafka consumers. What debugging problem remains?",
        [
            "The trace breaks across asynchronous boundaries, so end-to-end request flow cannot be reconstructed reliably.",
            "Kafka carries trace context automatically even when applications never forward headers.",
            "Asynchronous consumers do not need trace context because offsets already identify each message uniquely.",
            "Tracing matters only for synchronous HTTP calls, not event-driven pipelines.",
        ],
        "The trace breaks across asynchronous boundaries, so end-to-end request flow cannot be reconstructed reliably.",
        "Observability",
        ["observability", "tracing", "kafka"],
        ["java17", "java21"],
        7,
        8,
        "operations",
    ),
    make_supplement(
        "An SQS consumer times out after 25 seconds, but the queue visibility timeout is 20 seconds and duplicate processing appears. What is the main root cause?",
        [
            "Messages can become visible again before processing finishes, so another consumer can receive the same work.",
            "SQS deletes the message as soon as the consumer starts, so duplicates point to a client bug.",
            "Visibility timeout matters only for FIFO queues, not standard queues.",
            "The timeout mismatch affects CloudWatch alarms but not message delivery behavior.",
        ],
        "Messages can become visible again before processing finishes, so another consumer can receive the same work.",
        "Cloud Runtime Debugging",
        ["sqs", "visibility-timeout", "duplicates"],
        ["java17", "java21"],
        8,
        9,
        "operations",
    ),
    make_supplement(
        "Which remediation is strongest when retries and duplicate deliveries are already causing double-charging in a Java order workflow?",
        [
            "Make the handler idempotent and align queue visibility, retry, and processing-time settings so the system tolerates repeats safely.",
            "Increase only the JVM heap so each duplicate charge has more room to complete.",
            "Disable all retries globally so the workflow never sees the same order twice.",
            "Replace the queue with synchronous HTTP and rely on client timeouts for backpressure.",
        ],
        "Make the handler idempotent and align queue visibility, retry, and processing-time settings so the system tolerates repeats safely.",
        "Cloud Runtime Debugging",
        ["idempotency", "sqs", "retries"],
        ["java17", "java21"],
        8,
        4,
        "architecture",
    ),
    make_supplement(
        "A service retries outbound calls in the SDK, the HTTP client, and the workflow orchestrator. During a dependency outage, latency and queue depth spike everywhere. What is happening?",
        [
            "Retry multiplication is amplifying one failure into a broader platform incident.",
            "Independent retry layers always reduce total work because each layer backs off on its own.",
            "Queue depth cannot increase from retries unless the service uses synchronous JDBC.",
            "Latency spikes prove the dependency is healthy and callers are just over-provisioned.",
        ],
        "Retry multiplication is amplifying one failure into a broader platform incident.",
        "Cloud Runtime Debugging",
        ["retries", "latency", "incident-response"],
        ["java17", "java21"],
        8,
        9,
        "operations",
    ),
    make_supplement(
        "What is the strongest follow-up when a platform incident was caused by layered retries and no clear request correlation?",
        [
            "Consolidate retry ownership, add end-to-end correlation, and publish dependency-level latency metrics before the next rollout.",
            "Increase every timeout so retried requests have more time to pile up safely.",
            "Disable dashboards during incidents so teams focus only on raw logs.",
            "Move retries into finally blocks so they run after cleanup in every service.",
        ],
        "Consolidate retry ownership, add end-to-end correlation, and publish dependency-level latency metrics before the next rollout.",
        "Cloud Runtime Debugging",
        ["incident-response", "retries", "observability"],
        ["java17", "java21"],
        7,
        4,
        "operations",
    ),
    make_supplement(
        "A Java service writes only aggregate success counts to CloudWatch, so a partial regional outage hides behind a stable global average. What observability gap exists?",
        [
            "The metrics are missing dimensions that separate traffic by region, dependency, or failure class, so localized incidents stay masked.",
            "CloudWatch cannot store dimensional metrics for Java services unless X-Ray is enabled first.",
            "Regional outages always appear in global averages, so no additional dimensions are required.",
            "Aggregated metrics are preferable because dimensions make alarms less accurate under load.",
        ],
        "The metrics are missing dimensions that separate traffic by region, dependency, or failure class, so localized incidents stay masked.",
        "Observability",
        ["observability", "cloudwatch", "dimensions"],
        ["java17", "java21"],
        6,
        7,
        "operations",
    ),
]


JAVA_SHARED_SENIOR_THEORY_DEBUG_SUPPLEMENTS = [
    clone_supplement(
        JAVA_ENTRY_THEORY_SUPPLEMENTS[0],
        question_text="A service trims customer names with name.trim(); before logging, but the log still contains leading spaces. What explains the bug?",
    ),
    clone_supplement(JAVA_ENTRY_THEORY_SUPPLEMENTS[1]),
    clone_supplement(JAVA_ENTRY_THEORY_SUPPLEMENTS[2], topic="Streams Lambdas and Method References"),
    clone_supplement(JAVA_ENTRY_THEORY_SUPPLEMENTS[3], topic="Streams Lambdas and Method References"),
    clone_supplement(
        JAVA_ENTRY_THEORY_SUPPLEMENTS[4],
        question_text="A service catches Exception around file parsing and logs only e.getMessage();. Later, operations cannot tell whether the failure was validation, I/O, or configuration. What is the main problem?",
        topic="Practical Debugging",
    ),
    clone_supplement(JAVA_ENTRY_FUNDAMENTALS_SUPPLEMENTS[0], topic="Collections and Contracts"),
    clone_supplement(JAVA_ENTRY_FUNDAMENTALS_SUPPLEMENTS[1], topic="Collections and Contracts"),
    clone_supplement(JAVA_ENTRY_FUNDAMENTALS_SUPPLEMENTS[2]),
    clone_supplement(JAVA_ENTRY_FUNDAMENTALS_SUPPLEMENTS[3]),
    clone_supplement(
        JAVA_ENTRY_FUNDAMENTALS_SUPPLEMENTS[6],
        question_text="A scheduled executor keeps launching work, but the application never shuts down cleanly after the workload finishes. Which omission is the most likely cause?",
        topic="Concurrency and Executors",
    ),
    clone_supplement(JAVA_ENTRY_FUNDAMENTALS_SUPPLEMENTS[7], topic="Concurrency and Executors"),
    clone_supplement(JAVA_AWS_ADVANCED_SUPPLEMENTS[0], topic="Concurrency and Executors"),
    clone_supplement(JAVA_AWS_ADVANCED_SUPPLEMENTS[1], topic="Concurrency and Executors"),
    clone_supplement(JAVA_AWS_ADVANCED_SUPPLEMENTS[6]),
    clone_supplement(JAVA_AWS_ADVANCED_SUPPLEMENTS[7]),
    clone_supplement(JAVA_AWS_ADVANCED_SUPPLEMENTS[8], topic="Concurrency and Executors"),
    clone_supplement(JAVA_AWS_ADVANCED_SUPPLEMENTS[9], topic="Concurrency and Executors"),
]


BANK_SPECS = [
    {
        "bank_key": "java/java_entry_theory.json",
        "role_target": "java_entry",
        "round_target": "L2",
        "old_count": 95,
        "supplements": JAVA_ENTRY_THEORY_SUPPLEMENTS,
    },
    {
        "bank_key": "java/java_entry_fundamentals.json",
        "role_target": "java_entry",
        "round_target": "L3",
        "old_count": 92,
        "supplements": JAVA_ENTRY_FUNDAMENTALS_SUPPLEMENTS,
    },
    {
        "bank_key": "java/java_senior_theory_debug.json",
        "role_target": "java_shared_senior",
        "round_target": "L2",
        "old_count": 83,
        "supplements": JAVA_SHARED_SENIOR_THEORY_DEBUG_SUPPLEMENTS,
    },
    {
        "bank_key": "qa/java_qa_advanced.json",
        "role_target": "java_qa",
        "round_target": "L3",
        "old_count": 92,
        "supplements": JAVA_QA_ADVANCED_SUPPLEMENTS,
    },
    {
        "bank_key": "cloud/java_aws_cloud.json",
        "role_target": "java_aws",
        "round_target": "L3",
        "old_count": 68,
        "supplements": JAVA_AWS_CLOUD_SUPPLEMENTS,
    },
]


def build_all_banks():
    for spec in BANK_SPECS:
        old_pool = build_old_pool(spec["bank_key"], spec["role_target"], spec["round_target"])
        old_questions = select_old_questions(old_pool, spec["old_count"])
        combined = old_questions + [deepcopy(question) for question in spec["supplements"]]
        if len(combined) != 100:
            raise ValueError(f"{spec['bank_key']} has {len(combined)} questions instead of 100")
        finalized = finalize_questions(spec["bank_key"], spec["role_target"], spec["round_target"], combined)
        write_bank(spec["bank_key"], finalized)
        print(f"Wrote {spec['bank_key']} with {len(finalized)} questions")


if __name__ == "__main__":
    build_all_banks()
