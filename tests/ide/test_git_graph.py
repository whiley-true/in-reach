from in_reach.app.vcs import Snapshot
from in_reach.ide.git_graph import compute_lanes


def _snap(sha: str, *, parents: list[str] = (), branches: list[str] = (), stamp: str | None = None) -> Snapshot:
    return Snapshot(
        sha=sha,
        message=f"stamp: {stamp}" if stamp else f"commit {sha}",
        at=0.0,
        stamp_message=stamp,
        parents=list(parents),
        branches=list(branches),
    )


def test_a_linear_history_stays_on_a_single_lane() -> None:
    rows = compute_lanes(
        [
            _snap("c3", parents=["c2"]),
            _snap("c2", parents=["c1"]),
            _snap("c1", parents=[]),
        ]
    )

    assert [row.lane for row in rows] == [0, 0, 0]
    assert [row.continues for row in rows] == [True, True, False]
    # Nothing else was ever waiting on any of these shas -- every row's own incoming lane is just
    # its own straight-line continuation from the row above.
    assert [row.incoming_lanes for row in rows] == [[0], [0], [0]]


def test_two_branches_get_separate_lanes_until_they_share_a_fork_point() -> None:
    # feature forked off main at a1; main has since advanced to a3.
    rows = compute_lanes(
        [
            _snap("f1", parents=["a1"], branches=["feature"]),
            _snap("a3", parents=["a2"], branches=["main"]),
            _snap("a2", parents=["a1"]),
            _snap("a1", parents=[]),
        ]
    )
    by_sha = {row.snapshot.sha: row for row in rows}

    assert by_sha["f1"].lane == 0
    assert by_sha["a3"].lane == 1
    assert by_sha["a2"].lane == 1
    # a1 is the shared fork point -- both lane 0 (feature) and lane 1 (main-via-a2) converge here,
    # onto the lower lane number.
    assert by_sha["a1"].lane == 0
    assert sorted(by_sha["a1"].incoming_lanes) == [0, 1]
    assert by_sha["a1"].continues is False


def test_a_freed_lane_is_reused_by_a_later_independent_branch() -> None:
    # "short" is a one-commit branch that's already at its own root (no parent) -- it frees its lane
    # immediately. The next (older) row, an unrelated branch's own tip, should reuse that freed lane
    # rather than opening a brand new one, keeping the graph from growing wider than it needs to.
    rows = compute_lanes(
        [
            _snap("b1", parents=[], branches=["short"]),  # newest -- its own root, frees lane 0 at once
            _snap("a2", parents=["a1"], branches=["main"]),  # unrelated branch tip, processed next
            _snap("a1", parents=[]),
        ]
    )
    by_sha = {row.snapshot.sha: row for row in rows}

    assert by_sha["b1"].lane == 0
    assert by_sha["a2"].lane == 0  # reused, rather than allocating lane 1
    assert by_sha["a1"].lane == 0


def test_stamp_flag_and_branch_labels_are_preserved_on_the_row() -> None:
    rows = compute_lanes([_snap("s1", parents=[], branches=["main"], stamp="v1.0")])

    assert rows[0].snapshot.is_stamp is True
    assert rows[0].snapshot.stamp_message == "v1.0"
    assert rows[0].snapshot.branches == ["main"]


def test_active_lane_count_reflects_lanes_still_in_play() -> None:
    rows = compute_lanes(
        [
            _snap("f1", parents=["a1"], branches=["feature"]),
            _snap("a3", parents=["a2"], branches=["main"]),
        ]
    )

    # Both f1's and a3's own lanes are simultaneously active at this point in the walk.
    assert rows[1].active_lane_count == 2
