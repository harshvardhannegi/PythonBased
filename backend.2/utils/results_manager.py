import json
import os


class ResultsManager:
    def generate(
        self,
        repo_url,
        team_name,
        leader_name,
        branch,
        failures,
        fixes,
        timeline,
        retry_limit,
        total_commits,
        total_time_seconds,
        started_at,
        ended_at,
    ):

        final_status = timeline[-1]["status"] if timeline else "NO_RUNS"

        data = {
            "repo_url": repo_url,
            "team_name": team_name,
            "leader_name": leader_name,
            "branch_created": branch,
            "total_failures": failures,
            "total_fixes": fixes,
            "total_commits": total_commits,
            "final_status": final_status,
            "iterations": len(timeline),
            "retry_limit": retry_limit,
            "total_time_seconds": total_time_seconds,
            "started_at": started_at,
            "ended_at": ended_at,
            "timeline": timeline,
        }

        os.makedirs("results", exist_ok=True)

        with open("results/results.json", "w") as f:
            json.dump(data, f, indent=2)

    def load(self):

        try:
            with open("results/results.json") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
