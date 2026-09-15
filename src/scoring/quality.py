from typing import Optional

from src.models import Repository


def calculate_popularity_score(repo: Repository) -> float:
    stars = repo.stars or 0
    forks = repo.forks or 0
    contributors = (repo.activity or {}).get("contributors_90d", 0)

    if stars == 0:
        return 0.0

    stars_norm = min(stars / 100000, 1.0)
    forks_norm = min(forks / 10000, 1.0)
    contributors_norm = min(contributors / 20, 1.0)

    return (
        stars_norm * 0.4
        + forks_norm * 0.3
        + contributors_norm * 0.3
    ) * 100


def calculate_activity_score(
    last_push_days: int,
    commits_30d: int,
    releases_90d: int,
) -> float:
    if last_push_days <= 0 and commits_30d <= 0:
        return 0.0

    if last_push_days <= 7:
        push_score = 100
    elif last_push_days <= 30:
        push_score = 80
    elif last_push_days <= 90:
        push_score = 50
    else:
        push_score = 20

    if commits_30d >= 10:
        commits_score = 100
    elif commits_30d >= 3:
        commits_score = 70
    elif commits_30d >= 1:
        commits_score = 40
    else:
        commits_score = 10

    if releases_90d >= 5:
        releases_score = 100
    elif releases_90d >= 2:
        releases_score = 70
    elif releases_90d >= 1:
        releases_score = 40
    else:
        releases_score = 20

    return (push_score * 0.4 + commits_score * 0.3 + releases_score * 0.3)


def calculate_maintenance_score(
    has_readme: bool,
    has_license: bool,
    issue_response_days: Optional[int],
    last_commit_days: int,
) -> float:
    readme_score = 100 if has_readme else 0
    license_score = 100 if has_license else 0

    if issue_response_days is None:
        response_score = 30
    elif issue_response_days <= 7:
        response_score = 100
    elif issue_response_days <= 14:
        response_score = 80
    elif issue_response_days <= 30:
        response_score = 50
    else:
        response_score = 20

    if last_commit_days <= 7:
        commit_score = 100
    elif last_commit_days <= 30:
        commit_score = 80
    elif last_commit_days <= 90:
        commit_score = 50
    else:
        commit_score = 20

    return (
        readme_score * 0.25
        + license_score * 0.25
        + response_score * 0.25
        + commit_score * 0.25
    )


def calculate_community_score(
    contributors: int,
    forks: int,
    open_issues: int,
) -> float:
    contributors_norm = min(contributors / 20, 1.0)
    forks_norm = min(forks / 1000, 1.0)

    if open_issues > 500:
        issues_score = 20
    elif open_issues > 100:
        issues_score = 40
    elif open_issues > 10:
        issues_score = 70
    elif open_issues > 0:
        issues_score = 90
    else:
        issues_score = 100

    return (contributors_norm * 0.4 + forks_norm * 0.3 + (issues_score / 100) * 0.3) * 100