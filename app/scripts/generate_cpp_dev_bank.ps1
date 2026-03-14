$ErrorActionPreference = 'Stop'

$base = "app/services/question_bank/data"
$source = Join-Path $base "cpp/cpp_senior_theory_debug.json"
$target = Join-Path $base "cpp/cpp_dev_theory_debug.json"

$questions = @()
$global:idx = 1

function Add-Q {
    param(
        [string]$Question,
        [string[]]$Options,
        [string]$Correct,
        [string]$Topic,
        [string]$Difficulty,
        [string]$Style,
        [string[]]$Tags
    )

    $script:questions += [ordered]@{
        id = ("cpp-cpp-dev-l2-{0:000}" -f $global:idx)
        question = $Question
        options = $Options
        correct_answer = $Correct
        topic = $Topic
        difficulty = $Difficulty
        style = $Style
        tags = $Tags
        role_target = "cpp_dev"
        round_target = "L2"
        version_scope = @("cpp17", "gcc", "linux")
    }
    $global:idx++
}

# Seed with existing senior bank (100) but normalize for cpp_dev and avoid easy labels.
if (Test-Path $source) {
    $existing = Get-Content -Raw -Path $source | ConvertFrom-Json
    foreach ($q in $existing) {
        $q.id = ("cpp-cpp-dev-l2-{0:000}" -f $global:idx)
        $q.role_target = "cpp_dev"
        $q.round_target = "L2"
        if ($q.difficulty -eq "easy") { $q.difficulty = "medium" }
        $questions += $q
        $global:idx++
    }
}

# Template A: Name mangling / C linkage fixes (20)
$funcNames = @("log_event", "compute_crc", "init_device", "find_node", "serialize_state")
$params = @("int code", "const char* path", "uint32_t flags", "void* ctx")
foreach ($fname in $funcNames) {
    foreach ($param in $params) {
        $question = ("A C library exports 'void {0}({1})' compiled as C. A C++ file includes the header without extern ""C"" and the linker reports an undefined reference to a mangled symbol. What is the correct fix?" -f $fname, $param)
        $correct = "Wrap the declarations in an extern ""C"" block (guarded by __cplusplus) so C++ uses C linkage."
        Add-Q -Question $question -Options @(
            $correct,
            "Mark the function static in the header.",
            "Compile the C object file as C++ to match mangling.",
            "Add volatile qualifiers to the parameter types."
        ) -Correct $correct -Topic "Name Mangling and Linkage" -Difficulty "medium" -Style "concept" -Tags @("cpp_dev", "name_mangling", "linkage")
    }
}

# Template B: const and overload/mangling (20)
$baseTypes = @("int", "char", "Widget", "Node", "Buffer")
$overloads = @("apply", "update", "merge", "compute", "resolve")
foreach ($t in $baseTypes) {
    foreach ($fname in $overloads) {
        $question = ("You declare overloads 'void {0}({1}* p)' and 'void {0}(const {1}* p)'. Which statement is correct about overload resolution and mangling?" -f $fname, $t)
        $correct = "They are distinct overloads with different mangled names; const on the pointed-to type participates in overload resolution."
        Add-Q -Question $question -Options @(
            $correct,
            "const is ignored in parameter types; both declarations produce the same symbol.",
            "Only the return type affects mangling in this case.",
            "The compiler treats both as C linkage unless extern ""C"" is specified."
        ) -Correct $correct -Topic "Const Correctness and Overload Resolution" -Difficulty "medium" -Style "concept" -Tags @("cpp_dev", "const", "overload")
    }
}

# Template C: Using C code in C++ (extern "C" guards) (20)
$libHeaders = @("crypto", "device", "storage", "net", "vmbackup")
$headerFuncs = @("init", "shutdown", "reset", "load", "flush")
foreach ($lib in $libHeaders) {
    foreach ($fn in $headerFuncs) {
        $question = ("Header '{0}.h' (C) declares 'int {1}(void)'. It must compile in both C and C++. Which wrapper is correct?" -f $lib, $fn)
        $correct = "#ifdef __cplusplus`nextern ""C"" {`n#endif`nint $fn(void);`n#ifdef __cplusplus`n}`n#endif"
        Add-Q -Question $question -Options @(
            $correct,
            "namespace C { int $fn(void); }",
            "extern ""C++"" int $fn(void);",
            "static int $fn(void);"
        ) -Correct $correct -Topic "C/C++ Interop" -Difficulty "medium" -Style "concept" -Tags @("cpp_dev", "c_interop", "extern_c")
    }
}

# Template D: Using C++ from C via wrappers (20)
$classNames = @("BackupEngine", "PacketParser", "VmController", "CacheIndex", "ImageStore")
$resourceKinds = @("session", "handle", "context", "instance", "object")
foreach ($cls in $classNames) {
    foreach ($rk in $resourceKinds) {
        $question = ("C code must use a C++ class '{0}'. Which approach preserves ABI compatibility for C callers?" -f $cls)
        $correct = "Expose extern ""C"" functions that create/destroy and operate on an opaque {1} pointer wrapping the C++ object." -f $cls, $rk
        Add-Q -Question $question -Options @(
            $correct,
            "Include the C++ header directly in C and compile the C file as C99.",
            "Use name mangling to call methods directly from C.",
            "Mark all C++ methods as static and call them from C."
        ) -Correct $correct -Topic "C/C++ Interop" -Difficulty "hard" -Style "concept" -Tags @("cpp_dev", "c_interop", "abi")
    }
}

# Template E: vtable/vptr & virtual dispatch (debugging) (20)
$vtClasses = @("Base", "Device", "Renderer", "Pipeline", "Scheduler")
$vtMethods = @("tick", "render", "execute", "flush")
foreach ($cls in $vtClasses) {
    foreach ($m in $vtMethods) {
        $code = @"
struct $cls {
    virtual void $m();
    int id;
};
$cls obj;
std::cout << sizeof(obj);
"@
        $question = "Given the code:\n$code\nWhy is sizeof(obj) larger than an int?"
        $correct = "The object includes a vptr because it has a virtual function; the vtable is per-class, but each instance stores a pointer."
        Add-Q -Question $question -Options @(
            $correct,
            "The compiler duplicates the vtable inside each object, increasing size by the full table.",
            "Virtual functions are stored as inline lambdas inside the object.",
            "The size increases only because 'id' becomes 64-bit when virtual is used."
        ) -Correct $correct -Topic "Virtual Dispatch Internals" -Difficulty "hard" -Style "debugging" -Tags @("cpp_dev", "vtable", "debugging")
    }
}

# Template F: Diamond problem / virtual inheritance (20)
$diamondA = @("A", "Core", "Base", "Root", "Entity")
$diamondB = @("Left", "Reader", "Driver", "Node", "Alpha")
$diamondC = @("Right", "Writer", "Device", "Leaf", "Beta")
$diamondD = @("Diamond", "Adapter", "Manager", "Bridge", "Gamma")
for ($i = 0; $i -lt 20; $i++) {
    $a = $diamondA[$i % $diamondA.Count]
    $b = $diamondB[$i % $diamondB.Count]
    $c = $diamondC[$i % $diamondC.Count]
    $d = $diamondD[$i % $diamondD.Count]
    $question = ("Class {1} and {2} both inherit from {0}. {3} inherits from {1} and {2}. If {1} and {2} inherit {0} virtually, how many {0} subobjects does {3} contain?" -f $a, $b, $c, $d)
    $correct = ("Exactly one {0} subobject; it is constructed by the most-derived class {3}." -f $a, $b, $c, $d)
    Add-Q -Question $question -Options @(
        $correct,
        ("Two {0} subobjects; virtual inheritance only affects method dispatch." -f $a),
        ("One {0} subobject, but constructed twice (once per path)." -f $a),
        ("Zero {0} subobjects unless {3} explicitly names {0}." -f $a, $b, $c, $d)
    ) -Correct $correct -Topic "Multiple Inheritance" -Difficulty "medium" -Style "concept" -Tags @("cpp_dev", "diamond", "inheritance")
}

# Template G: Thread-safe singleton + even/odd threading (20)
$singleNames = @("Config", "Registry", "Logger", "Metrics", "Dispatcher")
foreach ($name in $singleNames) {
    $question = ("Which implementation is thread-safe in C++11 for a singleton '{0}' without extra locks?" -f $name)
    $correct = ("Use a function-local static: '{0}& instance() {{ static {0} inst; return inst; }}' (guaranteed thread-safe initialization)." -f $name)
    Add-Q -Question $question -Options @(
        $correct,
        "Use a raw static pointer with double-checked locking and no atomics.",
        "Allocate the instance lazily without synchronization because reads are atomic on x86.",
        "Use a global pointer and rely on order of initialization across translation units."
    ) -Correct $correct -Topic "Concurrency and Synchronization" -Difficulty "medium" -Style "concept" -Tags @("cpp_dev", "singleton", "threads")
}

$limits = @(100, 250, 500, 750, 1000)
foreach ($limit in $limits) {
    $code = @"
int n = $limit;
std::mutex m;
std::condition_variable cv;
int cur = 1;
bool even_turn = false;
// Thread A prints odd, Thread B prints even.
"@
    $question = "Given the setup:\n$code\nWhich condition is correct for each thread to avoid races and print 1..$limit in order?"
    $correct = "Odd thread waits while even_turn is true; even thread waits while even_turn is false; each increments cur and flips even_turn before notify_one()."
    Add-Q -Question $question -Options @(
        $correct,
        "Both threads wait on the same predicate 'cur % 2 == 0' and never toggle a turn flag.",
        "Use busy-waiting on cur without a mutex for better performance.",
        "Signal the condition variable without holding the mutex and without rechecking a predicate."
    ) -Correct $correct -Topic "Concurrency and Synchronization" -Difficulty "hard" -Style "debugging" -Tags @("cpp_dev", "threads", "condition_variable", "debugging")
}

# Template H: Shallow vs deep copy / copy ctor (debugging) (20)
$resourceNames = @("Buffer", "Frame", "Packet", "Blob", "Image")
$memberNames = @("data", "ptr", "payload", "bytes", "mem")
foreach ($r in $resourceNames) {
    foreach ($m in $memberNames) {
        $code = @"
struct $r {
    char* $m;
    $r(size_t n) { $m = new char[n]; }
    ~${r}() { delete[] $m; }
};
$r a(128);
$r b = a;
"@
        $question = "Given the code:\n$code\nWhat is the defect and the correct fix?"
        $correct = "The default copy performs a shallow copy, causing double delete; define a copy constructor/assignment (Rule of 3/5) or use smart pointers."
        Add-Q -Question $question -Options @(
            $correct,
            "The destructor should call delete instead of delete[].",
            "This is safe because each object owns its own buffer by default.",
            "The fix is to mark the copy constructor as noexcept."
        ) -Correct $correct -Topic "Copy and Move Semantics" -Difficulty "hard" -Style "debugging" -Tags @("cpp_dev", "copy", "debugging")
    }
}

# Template I: Pointer vs reference / stack vs heap (debugging) (20)
$returnTypes = @("int", "Node", "Widget", "Buffer", "Session")
$returnFuncs = @("get", "fetch", "load", "build", "create")
foreach ($t in $returnTypes) {
    foreach ($fn in $returnFuncs) {
        $code = @"
${t}& $fn() {
    $t tmp{};
    return tmp;
}
"@
        $question = "Given the code:\n$code\nWhat is the problem?"
        $correct = "It returns a reference to a stack-local object; the reference dangles after the function returns."
        Add-Q -Question $question -Options @(
            $correct,
            "Returning by reference always avoids copies and is safe here.",
            "The problem is only that tmp lacks a virtual destructor.",
            "The function should return a const reference to fix the lifetime."
        ) -Correct $correct -Topic "Pointers, References, and Lifetime" -Difficulty "hard" -Style "debugging" -Tags @("cpp_dev", "lifetime", "debugging")
    }
}

# Template J: BST level search (20)
function Get-BstLevel {
    param([int[]]$values, [int]$target)
    $root = $null
    function Insert-Node([ref]$node, [int]$value) {
        if ($null -eq $node.Value) {
            $node.Value = @{ v = $value; l = $null; r = $null }
            return
        }
        if ($value -lt $node.Value.v) {
            Insert-Node ([ref]$node.Value.l) $value
        } elseif ($value -gt $node.Value.v) {
            Insert-Node ([ref]$node.Value.r) $value
        }
    }
    foreach ($v in $values) {
        Insert-Node ([ref]$root) $v
    }
    # BFS
    $queue = New-Object System.Collections.Generic.Queue[object]
    if ($null -eq $root) { return -1 }
    $queue.Enqueue(@($root, 0))
    while ($queue.Count -gt 0) {
        $item = $queue.Dequeue()
        $node = $item[0]; $lvl = $item[1]
        if ($node.v -eq $target) { return $lvl }
        if ($node.l) { $queue.Enqueue(@($node.l, $lvl + 1)) }
        if ($node.r) { $queue.Enqueue(@($node.r, $lvl + 1)) }
    }
    return -1
}

$bstSequences = @(
    @(50, 30, 70, 20, 40, 60, 80),
    @(10, 5, 15, 3, 7, 12, 18),
    @(25, 10, 35, 5, 15, 30, 40, 13),
    @(90, 70, 110, 60, 80, 100, 120),
    @(42, 21, 63, 14, 28, 56, 70)
)
$targets = @(20, 40, 60, 80)
foreach ($seq in $bstSequences) {
    foreach ($t in $targets) {
        $level = Get-BstLevel -values $seq -target $t
        $question = "Insert the values " + ($seq -join ", ") + " into a BST. What level (root=0) is the value $t?"
        $correct = "Level $level"
        $d1 = [math]::Max(0, $level - 1)
        $d2 = $level + 1
        $d3 = $level + 2
        Add-Q -Question $question -Options @(
            $correct,
            "Level $d1",
            "Level $d2",
            "Level $d3"
        ) -Correct $correct -Topic "Data Structures - BST" -Difficulty "medium" -Style "concept" -Tags @("cpp_dev", "bst", "level")
    }
}

# Template K: VM backup classes (design patterns) (20)
$providers = @("VMware", "Hyper-V", "Windows VM", "KVM", "Xen")
$needs = @("incremental", "full", "snapshot", "differential")
foreach ($p in $providers) {
    foreach ($n in $needs) {
        $question = "You need to back up $p using $n strategy, and swap implementations without changing callers. Which pattern best fits the backup classes?"
        $correct = "Strategy (optionally created via a Factory) to select the backup algorithm at runtime."
        Add-Q -Question $question -Options @(
            $correct,
            "Singleton to ensure only one backup instance exists.",
            "Adapter to convert C++ to C without changing the API.",
            "Observer to notify all VMs during backup."
        ) -Correct $correct -Topic "Design Patterns" -Difficulty "medium" -Style "concept" -Tags @("cpp_dev", "design_patterns", "strategy")
    }
}

# Final sanity check for count
Write-Host "Generated" $questions.Count "questions"

$questions | ConvertTo-Json -Depth 6 | Set-Content -Path $target
Write-Host "Wrote" $target
