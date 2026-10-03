import pytest

from harness.safety import blocked


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "sudo rm -rf ~",
        "rm -fr $HOME",
        "rm --recursive /c",
        "cd /tmp && rm -rf /",
        'rm -rf "C:\\"',
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "shutdown -h now",
        "echo hi; reboot",
        "format C:",
        "bash <<EOF\nrm -rf /\nEOF",
        "cat > x.txt <<EOF\nnotes\nEOF\nrm -rf ~",
    ],
)
def test_destructive_commands_are_blocked(command):
    assert blocked(command)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build",
        "rm -rf ./node_modules /tmp/scratch",
        "rm /tmp/file",
        "ls /",
        "grep -r shutdown src/",
        "echo 'rm -rf /' > notes.txt && cat notes.txt",
        "dd if=a.img of=b.img",
        "git clean -fdx",
        "cat > notes.md <<'EOF'\n- safety.py catches mkfs, dd of=/dev/sda, shutdown and rm -rf /\nEOF",
        "python - <<PY\nprint('format C: is blocked; so is reboot')\nPY",
        "grep mk <<< 'here-string mentioning other things'",
    ],
)
def test_ordinary_commands_are_allowed(command):
    assert blocked(command) is None
