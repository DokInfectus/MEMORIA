#!/usr/bin/env bash

# MEMORIA_INSTALLER_LANGUAGE_PROMPT_V01
memoria_language_prompt_v01() {
    MEMORIA_INSTALL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    MEMORIA_INSTALL_ROOT="$(cd "${MEMORIA_INSTALL_SCRIPT_DIR}/.." && pwd)"
    MEMORIA_LANGUAGE_CONFIG="${MEMORIA_INSTALL_ROOT}/config/language.json"
    MEMORIA_LANGUAGE_TOOL="${MEMORIA_INSTALL_ROOT}/tools/memoria_language_config.py"

    if [ -f "${MEMORIA_LANGUAGE_CONFIG}" ]; then
        return 0
    fi

    if [ ! -f "${MEMORIA_LANGUAGE_TOOL}" ]; then
        echo "INFO Language config tool not found yet; continuing installer."
        return 0
    fi

    echo
    echo "MEMORIA language / Sprache"
    echo "----------------------------------------"
    echo "1) English"
    echo "2) Deutsch"
    echo

    if [ -n "${MEMORIA_LANGUAGE:-}" ]; then
        selected_language="${MEMORIA_LANGUAGE}"
        echo "Using MEMORIA_LANGUAGE=${selected_language}"
    elif [ -t 0 ]; then
        printf "Select language [1]: "
        read -r language_choice

        case "${language_choice}" in
            2|de|DE|deutsch|Deutsch)
                selected_language="de"
                ;;
            1|en|EN|english|English|"")
                selected_language="en"
                ;;
            *)
                selected_language="en"
                ;;
        esac
    else
        selected_language="en"
        echo "INFO Non-interactive installer: defaulting language to English."
    fi

    python3 "${MEMORIA_LANGUAGE_TOOL}" set "${selected_language}"
}

memoria_language_prompt_v01


set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT" || exit 1

MODE_INPUT=""
SELECTED_MODE=""
MODE_FROM_CLI="no"

MATRIX_UI_INPUT=""
MATRIX_UI_ENABLED="no"

FEATURE_PROFILE_INPUT=""
FEATURE_PROFILE="minimal"
OCR_ENABLED="no"

print_help() {
    echo "MEMORIA Installer V1.2"
    echo ""
    echo "Usage:"
    echo "  bash scripts/install.sh"
    echo "  bash scripts/install.sh --mode llama-cpp-direct"
    echo "  bash scripts/install.sh --mode open-webui"
    echo "  bash scripts/install.sh --mode ollama"
    echo "  bash scripts/install.sh --mode doctor-only"
    echo "  bash scripts/install.sh --mode manual-advanced"
    echo "  bash scripts/install.sh --doctor-only"
    echo "  bash scripts/install.sh --mode llama-cpp-direct --matrix-ui"
    echo ""
    echo "Options:"
    echo "  --features PROFILE"
    echo "      minimal"
    echo "      matrix-ui"
    echo ""
    echo "  Local OCR is implemented but not enabled as a public feature profile."
    echo ""
    echo "Compatibility options:"
    echo "  --matrix-ui       maps to feature profile matrix-ui"
    echo "  --no-matrix-ui    maps to feature profile minimal"
    echo ""
    echo "Modes:"
    echo "  doctor-only"
    echo "  llama-cpp-direct"
    echo "  open-webui"
    echo "  ollama"
    echo "  manual-advanced"
    echo ""
}

normalize_mode() {
    case "$1" in
        1|doctor|doctor-only|--doctor-only)
            SELECTED_MODE="doctor-only"
            ;;
        2|llama|llamacpp|llama-cpp|llama-cpp-direct)
            SELECTED_MODE="llama-cpp-direct"
            ;;
        3|openwebui|open-webui|webui)
            SELECTED_MODE="open-webui"
            ;;
        4|ollama)
            SELECTED_MODE="ollama"
            ;;
        5|manual|advanced|manual-advanced)
            SELECTED_MODE="manual-advanced"
            ;;
        *)
            echo ""
            echo "ERROR: Invalid mode: $1"
            echo ""
            print_help
            exit 1
            ;;
    esac
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --help|-h)
                print_help
                exit 0
                ;;
            --doctor-only)
                MODE_INPUT="doctor-only"
                MODE_FROM_CLI="yes"
                shift
                ;;
            --mode)
                if [ "$#" -lt 2 ]; then
                    echo "ERROR: --mode requires a value."
                    exit 1
                fi

                MODE_INPUT="$2"
                MODE_FROM_CLI="yes"
                shift 2
                ;;
            --features)
                if [ "$#" -lt 2 ]; then
                    echo "ERROR: --features requires a value."
                    exit 1
                fi

                FEATURE_PROFILE_INPUT="$2"
                shift 2
                ;;
            --matrix-ui)
                MATRIX_UI_INPUT="yes"
                shift
                ;;
            --no-matrix-ui)
                MATRIX_UI_INPUT="no"
                shift
                ;;
            *)
                echo "ERROR: Unknown argument: $1"
                echo ""
                print_help
                exit 1
                ;;
        esac
    done
}

interactive_mode_select() {
    echo ""
    echo "Step 5: Select setup mode"
    echo ""
    echo "1) Doctor only"
    echo "2) llama.cpp Direct"
    echo "3) Open WebUI"
    echo "4) Ollama"
    echo "5) Manual / Advanced"
    echo ""

    read -r -p "Select mode [1-5]: " MODE_INPUT

    normalize_mode "$MODE_INPUT"
}

run_doctor() {
    python3 tools/memoria_doctor.py
    return "$?"
}

run_install_consent_gate() {
    echo ""
    echo "Step 2b: MEMORIA local data consent..."
    echo ""

    if [ ! -f "tools/memoria_install_consent.py" ]; then
        echo "ERROR: Install consent tool missing."
        exit 1
    fi

    if python3 tools/memoria_install_consent.py status >/dev/null 2>&1; then
        echo "Install consent: already accepted."
        return 0
    fi

    echo "Install consent: required."

    if [ "${MEMORIA_ACCEPT_LOCAL_TERMS:-}" = "ACCEPT" ]; then
        python3 tools/memoria_install_consent.py accept --yes
        return "$?"
    fi

    if [ -t 0 ]; then
        python3 tools/memoria_install_consent.py accept
        return "$?"
    fi

    echo "ABORT: MEMORIA local data terms must be accepted before installation."
    echo "Run installer interactively, or for scripted installs use:"
    echo "MEMORIA_ACCEPT_LOCAL_TERMS=ACCEPT bash scripts/install.sh --mode doctor-only"
    exit 2
}

normalize_yes_no() {
    case "$1" in
        y|Y|yes|YES|j|J|ja|JA)
            MATRIX_UI_ENABLED="yes"
            ;;
        n|N|no|NO|nein|NEIN|"")
            MATRIX_UI_ENABLED="no"
            ;;
        *)
            echo "ERROR: Invalid Matrix UI choice: $1"
            echo "Use yes/no."
            exit 1
            ;;
    esac
}

normalize_feature_profile() {
    case "$1" in
        1|minimal)
            FEATURE_PROFILE="minimal"
            ;;
        2|matrix|matrix-ui)
            FEATURE_PROFILE="matrix-ui"
            ;;
        3|4|ocr|local-ocr|full|matrix-ui+ocr|matrix-ui-ocr)
            echo "ERROR: Local OCR is implemented but not enabled as a public feature profile."
            echo "Use minimal or matrix-ui."
            exit 1
            ;;
        *)
            echo "ERROR: Invalid feature profile: $1"
            echo "Use minimal or matrix-ui."
            exit 1
            ;;
    esac
}

apply_feature_profile() {
    MATRIX_UI_ENABLED="no"
    OCR_ENABLED="no"

    case "$FEATURE_PROFILE" in
        minimal)
            ;;
        matrix-ui)
            MATRIX_UI_ENABLED="yes"
            ;;
        local-ocr)
            OCR_ENABLED="yes"
            ;;
        matrix-ui+ocr)
            MATRIX_UI_ENABLED="yes"
            OCR_ENABLED="yes"
            ;;
        *)
            echo "ERROR: Internal invalid feature profile: $FEATURE_PROFILE"
            exit 1
            ;;
    esac
}

interactive_feature_profile_select() {
    echo ""
    echo "Step 6a: Select optional MEMORIA features"
    echo ""
    echo "1) Minimal"
    echo "   Terminal Cockpit only"
    echo ""
    echo "2) Matrix UI"
    echo "   Terminal Cockpit + graphical Matrix interface"
    echo ""

    read -r -p "Select feature profile [1-2]: " FEATURE_PROFILE_INPUT

    normalize_feature_profile "$FEATURE_PROFILE_INPUT"
    apply_feature_profile
}

resolve_feature_profile() {
    if [ -n "$FEATURE_PROFILE_INPUT" ] && [ -n "$MATRIX_UI_INPUT" ]; then
        echo "ERROR: Do not combine --features with --matrix-ui/--no-matrix-ui."
        exit 1
    fi

    if [ -n "$FEATURE_PROFILE_INPUT" ]; then
        normalize_feature_profile "$FEATURE_PROFILE_INPUT"
        apply_feature_profile
        return 0
    fi

    if [ -n "$MATRIX_UI_INPUT" ]; then
        normalize_yes_no "$MATRIX_UI_INPUT"

        if [ "$MATRIX_UI_ENABLED" = "yes" ]; then
            FEATURE_PROFILE="matrix-ui"
        else
            FEATURE_PROFILE="minimal"
        fi

        apply_feature_profile
        return 0
    fi

    if [ "$MODE_FROM_CLI" = "yes" ]; then
        FEATURE_PROFILE="minimal"
        apply_feature_profile
        return 0
    fi

    interactive_feature_profile_select
}

interactive_matrix_ui_select() {
    echo ""
    echo "Step 6d: Optional Matrix GUI support"
    echo ""
    echo "Terminal Cockpit is the default for headless systems."
    echo "Matrix GUI requires tkinter and a graphical display or VNC/noVNC."
    echo "No GUI service will be started automatically."
    echo ""

    read -r -p "Enable Matrix GUI support check? [y/N]: " MATRIX_UI_INPUT

    normalize_yes_no "$MATRIX_UI_INPUT"
}

run_package_flow_preview() {
    echo ""
    echo "Step 6b: MEMORIA package flow preview..."
    echo ""
    echo "Feature profile:"
    echo "$FEATURE_PROFILE"
    echo ""
    echo "This stage is preview-only."
    echo "No package installation is permitted."
    echo ""

    PACKAGE_FLOW_FILES=(
        "tools/memoria_platform_detector.py"
        "tools/memoria_package_profile.py"
        "tools/memoria_package_confirmation.py"
        "tools/memoria_package_install_plan.py"
        "tools/memoria_package_approval_handoff.py"
    )

    for file in "${PACKAGE_FLOW_FILES[@]}"; do
        if [ ! -f "$file" ]; then
            echo "ERROR: Required package-flow tool missing: $file"
            return 1
        fi
    done

    echo "---- Platform Detection ----"
    python3 tools/memoria_platform_detector.py --json
    PACKAGE_FLOW_STATUS="$?"

    if [ "$PACKAGE_FLOW_STATUS" -ne 0 ]; then
        echo "ERROR: Platform Detector preview failed."
        return 1
    fi

    echo ""
    echo "---- Package Profile ----"
    PYTHONPATH=tools python3 tools/memoria_package_profile.py \
        --feature "$FEATURE_PROFILE" \
        --json
    PACKAGE_FLOW_STATUS="$?"

    if [ "$PACKAGE_FLOW_STATUS" -ne 0 ]; then
        echo "ERROR: Package Profile preview failed."
        return 1
    fi

    echo ""
    echo "---- Confirmation Preview ----"
    PYTHONPATH=tools python3 tools/memoria_package_confirmation.py \
        --feature "$FEATURE_PROFILE" \
        --preview
    PACKAGE_FLOW_STATUS="$?"

    if [ "$PACKAGE_FLOW_STATUS" -eq 3 ]; then
        echo ""
        echo "Package confirmation preview: BLOCKED by platform policy."
        echo "No package installation will be attempted."
    elif [ "$PACKAGE_FLOW_STATUS" -ne 0 ]; then
        echo "ERROR: Package Confirmation preview failed."
        return 1
    fi

    echo ""
    echo "---- Installation Plan ----"
    PYTHONPATH=tools python3 tools/memoria_package_install_plan.py \
        --feature "$FEATURE_PROFILE" \
        --json
    PACKAGE_FLOW_STATUS="$?"

    if [ "$PACKAGE_FLOW_STATUS" -ne 0 ]; then
        echo "ERROR: Installation Plan preview failed."
        return 1
    fi

    echo ""
    echo "---- Approval Handoff Preview ----"
    PYTHONPATH=tools python3 tools/memoria_package_approval_handoff.py \
        --feature "$FEATURE_PROFILE" \
        --preview
    PACKAGE_FLOW_STATUS="$?"

    if [ "$PACKAGE_FLOW_STATUS" -ne 0 ]; then
        echo "ERROR: Approval Handoff preview failed."
        return 1
    fi

    echo ""
    echo "===== PACKAGE FLOW PREVIEW RESULT ====="
    echo "Package flow: DRY RUN ONLY"
    echo "Approval handoff: PREVIEW ONLY"
    echo "Package installation: BLOCKED"
    echo "No packages were installed."
    echo "No system configuration was changed."
    echo ""

    return 0
}

run_matrix_ui_preflight() {
    echo ""
    echo "Step 6d: Matrix GUI support..."
    echo ""

    if [ "$MATRIX_UI_ENABLED" != "yes" ]; then
        echo "Matrix GUI support: disabled."
        echo "Terminal Cockpit remains the default admin interface."
        return 0
    fi

    echo "Matrix GUI support: requested."
    echo "Running read-only Matrix UI Doctor if available."
    echo ""

    MATRIX_FILES=(
        "tools/memoria_matrix_ui.py"
        "tools/memoria_matrix_ui_doctor.py"
        "tools/memoria_matrix_ui_control.py"
    )

    COMPILE_FILES=()

    for file in "${MATRIX_FILES[@]}"; do
        if [ -f "$file" ]; then
            COMPILE_FILES+=("$file")
        fi
    done

    if [ "${#COMPILE_FILES[@]}" -gt 0 ]; then
        python3 -m py_compile "${COMPILE_FILES[@]}"

        if [ "$?" -ne 0 ]; then
            echo "WARNING: Matrix UI module compile check reported an error."
            return 0
        fi
    fi

    if [ -f "tools/memoria_matrix_ui_doctor.py" ]; then
        python3 tools/memoria_matrix_ui_doctor.py
        MATRIX_UI_STATUS="$?"

        if [ "$MATRIX_UI_STATUS" -ne 0 ]; then
            echo ""
            echo "WARNING: Matrix UI Doctor reported an issue."
            echo "Terminal Cockpit remains available."
        fi
    else
        echo "WARNING: Matrix UI Doctor not found."
        echo "Terminal Cockpit remains available."
    fi

    echo ""
    echo "Matrix GUI note:"
    echo "- Installer does not start VNC/noVNC automatically."
    echo "- Use Matrix UI Control after install if you want to start it."
}

run_package_install_cli() {
    echo ""
    echo "Step 6c: MEMORIA package installation..."
    echo ""

    if [ ! -f "tools/memoria_package_install_cli.py" ]; then
        echo "ERROR: Package Install CLI tool missing."
        echo "Package installation cannot continue."
        return 1
    fi

    echo "Package approval, transaction verification and execution"
    echo "remain inside the verified Python package-install chain."
    echo "The installer owns no direct package execution logic."
    echo ""

    if [ "$SELECTED_MODE" = "doctor-only" ]; then
        echo "Doctor-only mode keeps the package stage system-change free."
        echo "Package profile preview above remains informational."
        echo "Package install CLI: SKIPPED (DOCTOR ONLY)"
        echo "Package installation: SKIPPED"
        return 0
    fi

    PYTHONPATH=tools python3 \
        tools/memoria_package_install_cli.py \
        --feature "$FEATURE_PROFILE"

    PACKAGE_INSTALL_RESULT="$?"

    echo ""

    case "$PACKAGE_INSTALL_RESULT" in
        0)
            echo "Package install CLI: EXECUTION COMPLETED"
            echo "Package installation: COMPLETED"
            return 0
            ;;
        *)
            echo "Package install CLI: STOPPED"
            echo "Status: $PACKAGE_INSTALL_RESULT"
            echo "See MEMORIA PACKAGE INSTALL CLI result above"
            echo "for the authoritative execution state."
            return "$PACKAGE_INSTALL_RESULT"
            ;;
    esac
}

parse_args "$@"

echo "=== MEMORIA INSTALLER V1.2 ==="
echo ""
echo "Project root:"
echo "$PROJECT_ROOT"
echo ""

echo "Step 1: Checking Python..."

if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION="$(python3 --version)"
    echo "OK: $PYTHON_VERSION"
else
    echo "ERROR: python3 not found."
    echo "Please install Python 3 first."
    exit 1
fi

echo ""
echo "Step 2: Checking project structure..."

REQUIRED_PATHS=(
    "diagnostics"
    "doctor"
    "tools/memoria_doctor.py"
    "tools/memoria_install_consent.py"
    "tools/memoria_platform_detector.py"
    "tools/memoria_package_profile.py"
    "tools/memoria_package_confirmation.py"
    "tools/memoria_package_install_plan.py"
    "tools/memoria_package_approval_handoff.py"
    "tools/memoria_package_execution_gate.py"
    "tools/memoria_package_executor.py"
    "tools/memoria_package_execution_flow.py"
    "tools/memoria_package_transaction_preview.py"
    "tools/memoria_package_transaction_approval.py"
    "tools/memoria_package_system_change_authorization.py"
    "tools/memoria_package_system_change_runner.py"
    "tools/memoria_package_install_orchestrator.py"
    "tools/memoria_package_install_cli.py"
    "docs"
    "docs/MEMORIA_LOCAL_TERMS.md"
    "scripts"
)

STRUCTURE_OK=1

for path in "${REQUIRED_PATHS[@]}"; do
    if [ -e "$PROJECT_ROOT/$path" ]; then
        echo "OK: $path"
    else
        echo "ERROR: Missing $path"
        STRUCTURE_OK=0
    fi
done

if [ "$STRUCTURE_OK" -ne 1 ]; then
    echo ""
    echo "Project structure check failed."
    exit 1
fi

run_install_consent_gate

echo ""
echo "Step 3: Compiling important modules..."

PYTHON_FILES=(
    "diagnostics/exceptions.py"
    "diagnostics/backend.py"
    "diagnostics/manager.py"
    "doctor/exceptions.py"
    "doctor/builder.py"
    "doctor/manager.py"
    "tools/memoria_doctor.py"
    "tools/memoria_install_consent.py"
    "tools/memoria_platform_detector.py"
    "tools/memoria_package_profile.py"
    "tools/memoria_package_confirmation.py"
    "tools/memoria_package_install_plan.py"
    "tools/memoria_package_approval_handoff.py"
    "tools/memoria_package_execution_gate.py"
    "tools/memoria_package_executor.py"
    "tools/memoria_package_execution_flow.py"
    "tools/memoria_package_transaction_preview.py"
    "tools/memoria_package_transaction_approval.py"
    "tools/memoria_package_system_change_authorization.py"
    "tools/memoria_package_system_change_runner.py"
    "tools/memoria_package_install_orchestrator.py"
    "tools/memoria_package_install_cli.py"
)

python3 -m py_compile "${PYTHON_FILES[@]}"

if [ "$?" -ne 0 ]; then
    echo ""
    echo "ERROR: Python module compile check failed."
    exit 1
fi

echo "OK: Python modules compiled successfully."

echo ""
echo "Step 4: Running MEMORIA Doctor..."
echo ""

run_doctor
DOCTOR_STATUS="$?"

if [ "$DOCTOR_STATUS" -ne 0 ]; then
    echo ""
    echo "WARNING: MEMORIA Doctor reported an error."
    echo "You can still continue, but setup may not be ready."
fi

if [ -n "$MODE_INPUT" ]; then
    normalize_mode "$MODE_INPUT"
    echo ""
    echo "Step 5: Setup mode provided by command line."
else
    interactive_mode_select
fi

echo ""
echo "Selected mode:"
echo "$SELECTED_MODE"

resolve_feature_profile

echo ""
echo "Selected feature profile:"
echo "$FEATURE_PROFILE"
echo ""
echo "Matrix GUI support:"
echo "$MATRIX_UI_ENABLED"
echo ""
echo "Local OCR support:"
echo "$OCR_ENABLED"

run_package_flow_preview
PACKAGE_PREVIEW_STATUS="$?"

if [ "$PACKAGE_PREVIEW_STATUS" -ne 0 ]; then
    echo ""
    echo "ERROR: MEMORIA package flow preview reported an error."
    echo "No package installation was attempted."
    exit 1
fi

run_package_install_cli
PACKAGE_INSTALL_STATUS="$?"

if [ "$PACKAGE_INSTALL_STATUS" -ne 0 ]; then
    echo ""
    echo "MEMORIA setup stopped by package install CLI."
    echo "Review the authoritative CLI result above"
    echo "before any new installation attempt."
    exit "$PACKAGE_INSTALL_STATUS"
fi

run_matrix_ui_preflight

echo ""
echo "Step 7: Post-install validation..."
echo ""

run_doctor
POST_STATUS="$?"

echo ""
echo "=== MEMORIA INSTALLER RESULT ==="
echo ""

if [ "$POST_STATUS" -eq 0 ]; then
    echo "Install check completed."
else
    echo "Install check completed with warnings."
fi

echo ""
echo "Selected mode:"
echo "$SELECTED_MODE"

echo ""
echo "Next recommended command:"
echo "python3 tools/memoria_doctor.py"

echo ""
echo "CLI examples:"
echo "bash scripts/install.sh --mode llama-cpp-direct"
echo "bash scripts/install.sh --doctor-only"
echo "bash scripts/install.sh --mode llama-cpp-direct --matrix-ui"

echo ""
echo "Notes:"
echo "- No private chats were read."
echo "- No tokens were printed."
echo "- No personas were printed."
echo "- No configuration was changed automatically."
echo "- No telemetry was sent."
echo "- No GUI services were started automatically."

echo ""
echo "=== END ==="

exit "$POST_STATUS"
