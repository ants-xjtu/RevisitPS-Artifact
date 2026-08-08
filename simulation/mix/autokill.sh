#!/bin/bash

# #############################################################################
# Script: kill_ns3_sims.sh (v2)
# Description: Reads an ns-3 simulation log file, extracts session IDs,
#              finds all corresponding running processes, and kills them.
# Author: Gemini
# Change: Now correctly handles multiple PIDs for a single session ID.
# #############################################################################

# --- Configuration ---
# Set colors for better output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- Functions ---

# Function to display how to use the script
usage() {
    echo -e "${YELLOW}Usage:${NC} $0 [options] <log_file>"
    echo
    echo -e "This script reads a simulation log file to find and kill running ns-3 processes."
    echo
    echo -e "${YELLOW}Options:${NC}"
    echo -e "  ${GREEN}--dry-run${NC}     Show which processes would be killed, but don't actually kill them."
    echo -e "  ${GREEN}--force${NC}       Use 'kill -9' (SIGKILL) for a forceful termination. Default is 'kill -15'."
    echo -e "  ${GREEN}-h, --help${NC}    Display this help message."
    echo
    echo -e "${YELLOW}Example:${NC}"
    echo -e "  # See what would be killed (safe mode)"
    echo -e "  $0 --dry-run my_simulation.log"
    echo
    echo -e "  # Kill all processes found in the log"
    echo -e "  $0 my_simulation.log"
    echo
    echo -e "  # Force kill all processes"
    echo -e "  $0 --force my_simulation.log"
    exit 1
}

# --- Main Logic ---

# Initialize variables with default values
DRY_RUN=false
FORCE_KILL=false
LOG_FILE=""

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=true; shift ;;
        --force) FORCE_KILL=true; shift ;;
        -h|--help) usage ;;
        -*) echo "Unknown option: $1"; usage ;;
        *) LOG_FILE="$1"; shift ;;
    esac
done

# Check if log file was provided
if [ -z "$LOG_FILE" ]; then
    echo -e "${RED}Error: Log file not specified.${NC}"
    usage
fi

# Check if log file exists
if [ ! -f "$LOG_FILE" ]; then
    echo -e "${RED}Error: Log file '$LOG_FILE' not found.${NC}"
    exit 1
fi

echo "Reading log file: $LOG_FILE"
echo "----------------------------------------"

# Extract unique IDs from the log file using grep and cut
SESSION_IDS=$(grep '^[0-9]\{2\}/[0-9]\{2\}/[0-9]\{2\}' "$LOG_FILE" | cut -d',' -f2 | sort -u)

if [ -z "$SESSION_IDS" ]; then
    echo -e "${YELLOW}No session IDs found in the log file. Exiting.${NC}"
    exit 0
fi

# Loop through each session ID found in the log
for id in $SESSION_IDS; do
    echo -e "🔎 Processing session ID: ${YELLOW}$id${NC}"

    # Construct the unique pattern to search for in the process list
    SEARCH_PATTERN="/mix/output/${id}/config.txt"

    # Find all process IDs (PIDs) matching the pattern. This might return multiple PIDs.
    PID_LIST=$(ps -ef | grep "$SEARCH_PATTERN" | grep -v grep | awk '{print $2}')

    if [ -n "$PID_LIST" ]; then
        # Loop through each found PID
        for pid_to_kill in $PID_LIST; do
            echo -e "  ✅ Found running process with PID: ${GREEN}$pid_to_kill${NC}"
            
            # Display process details for confirmation
            ps -f -p "$pid_to_kill" | tail -n +2
            
            if [ "$DRY_RUN" = true ]; then
                echo -e "  ${YELLOW}[DRY RUN] Would kill process $pid_to_kill.${NC}"
            else
                # Determine kill signal
                if [ "$FORCE_KILL" = true ]; then
                    SIGNAL="-9"
                    ACTION="Force killing (SIGKILL)"
                else
                    SIGNAL="-15"
                    ACTION="Terminating (SIGTERM)"
                fi

                echo -e "  ${RED}🛑 $ACTION process $pid_to_kill...${NC}"
                kill "$SIGNAL" "$pid_to_kill"
                
                # Check if kill command was successful
                if [ $? -eq 0 ]; then
                    echo -e "  ${GREEN}Signal sent successfully.${NC}"
                else
                    echo -e "  ${RED}Failed to send signal. The process might require sudo or may have already exited.${NC}"
                fi
            fi
        done
    else
        # If no PID is found for the ID
        echo -e "  ❌ Process for session ID $id not found. It might have already finished."
    fi
    echo "----------------------------------------"
done

echo "Script finished."