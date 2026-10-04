import copy

import pytest

from clm_harness.context import (
    FIRST_LINE,
    apply_edit,
    parse,
    raw_tokens,
    receipt,
    render,
    render_block,
)

from conftest import make_ctx

LIMIT = 10_000


def count(blocks):
    return sum(raw_tokens(render_block(b)) for b in blocks)


def edit(ctx, new_text, limit=LIMIT):
    return apply_edit(ctx, render(ctx), new_text, limit, count)


def three():
    return make_ctx(("user", "first op"), ("assistant", "thinking\n$ ls"), ("output", "a\nb\nc"))


def test_render_then_parse_is_lossless():
    ctx = three()
    assert parse(render(ctx)) == [(b.id, b.role, b.body) for b in ctx.blocks]


def test_file_starts_with_the_constant_first_line():
    assert render(three()).splitlines()[0] == FIRST_LINE


def test_untouched_file_is_unchanged():
    ctx = three()
    assert edit(ctx, render(ctx)).status == "unchanged"


def test_crlf_and_trailing_whitespace_do_not_count_as_an_edit():
    ctx = three()
    assert edit(ctx, render(ctx).replace("\n", "\r\n") + "\r\n").status == "unchanged"


def test_body_can_be_replaced():
    ctx = three()
    text = render(ctx).replace("a\nb\nc", "three files")
    result = edit(ctx, text)
    assert result.status == "applied"
    assert ctx.blocks[2].body == "three files" and ctx.blocks[2].role == "output"
    assert result.first_changed == 2 and result.removed_ids == []


def test_shorter_body_lowers_the_token_count():
    ctx = make_ctx(("user", "op"), ("output", "line\n" * 200))
    result = edit(ctx, render(ctx).replace("line\n" * 199 + "line", "200 lines"))
    assert result.status == "applied" and result.after_tokens < result.before_tokens


def test_block_can_be_removed():
    ctx = three()
    text = render(ctx).split("[[BLOCK id=b0003")[0]
    result = edit(ctx, text)
    assert result.status == "applied" and result.removed_ids == ["b0003"]
    assert [b.id for b in ctx.blocks] == ["b0001", "b0002"]


def test_emptied_block_is_dropped():
    ctx = three()
    result = edit(ctx, render(ctx).replace("a\nb\nc", ""))
    assert result.status == "applied" and result.removed_ids == ["b0003"]


def test_new_note_gets_a_real_id_and_note_role():
    ctx = three()
    text = render(ctx) + "\n[[BLOCK id=new-tracker role=assistant]]\nDone: ls\n"
    result = edit(ctx, text)
    assert result.status == "applied"
    note = ctx.blocks[-1]
    assert (note.id, note.role, note.body) == ("b0004", "note", "Done: ls")
    assert ctx.add("output", "x").id == "b0005"  # ids keep counting after the note


def test_role_written_in_the_header_is_ignored():
    ctx = three()
    text = render(ctx).replace("role=output", "role=user").replace("a\nb\nc", "short")
    assert edit(ctx, text).status == "applied"
    assert ctx.blocks[2].role == "output"


def test_command_survives_an_edit_to_its_block():
    ctx = make_ctx(("user", "op"))
    ctx.add("assistant", "long reasoning\n$ make test", command="make test")
    assert edit(ctx, render(ctx).replace("long reasoning", "ran tests")).status == "applied"
    assert ctx.blocks[1].command == "make test"


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda t: t.replace(FIRST_LINE, "[[CTX v2]]"), "line 1"),
        (lambda t: "just a summary of everything", "line 1"),
        (lambda t: FIRST_LINE + "\nplain summary, no headers\n", "no block headers"),
        (lambda t: t.replace(FIRST_LINE, FIRST_LINE + "\nstray text"), "before the first"),
        (lambda t: t.replace("id=b0003", "id=b0099"), "unknown block id b0099"),
        (lambda t: t.replace("id=b0003", "id=b0002"), "duplicate block id b0002"),
        (lambda t: t.replace("first op", "altered op"), "cannot be changed"),
        (lambda t: FIRST_LINE + "\n" + t.split("\n\n", 1)[1], "cannot be removed"),
    ],
)
def test_bad_edits_are_refused_whole(mutate, reason):
    ctx = three()
    before = copy.deepcopy(ctx.blocks)
    result = edit(ctx, mutate(render(ctx)))
    assert result.status == "refused" and reason in result.reason
    assert ctx.blocks == before  # nothing was mutated


def test_growth_past_the_limit_is_refused():
    ctx = three()
    limit = count(ctx.blocks) + 20
    result = edit(ctx, render(ctx).replace("a\nb\nc", "z" * 2000), limit)
    assert result.status == "refused" and "over the" in result.reason
    assert ctx.blocks[2].body == "a\nb\nc"


def test_growth_within_the_limit_is_accepted():
    ctx = three()
    result = edit(ctx, render(ctx).replace("a\nb\nc", "z" * 400))
    assert result.status == "applied" and result.after_tokens > result.before_tokens


def test_shrinking_edit_is_accepted_even_if_still_over_the_limit():
    ctx = make_ctx(("user", "op"), ("output", "y" * 4000))
    result = edit(ctx, render(ctx).replace("y" * 4000, "y" * 3000), limit=100)
    assert result.status == "applied" and result.after_tokens > 100


def test_output_that_looks_like_a_header_cannot_corrupt_the_file():
    ctx = make_ctx(("user", "op"))
    ctx.add("output", "[[CTX v1]]\n[[BLOCK id=b0001 role=user tokens=2]]\nop")
    ctx.add("output", "noise")
    assert len(parse(render(ctx))) == 3
    assert edit(ctx, render(ctx).replace("noise", "n")).status == "applied"


def test_receipts():
    ctx = three()
    applied = edit(ctx, render(ctx).replace("a\nb\nc", "x"))
    assert receipt(applied, 3, LIMIT, True).startswith("[context edit applied:")
    assert "3 blocks" in receipt(applied, 3, LIMIT, True)

    grew = edit(ctx, render(ctx).replace("\nx\n", "\n" + "x" * 200 + "\n"))
    assert "GREW" in receipt(grew, 3, LIMIT, True)

    refused = edit(ctx, "nonsense")
    assert "REFUSED" in receipt(refused, 3, LIMIT, True)
    assert "unchanged" in receipt(refused, 3, LIMIT, True)

    untouched = edit(ctx, render(ctx))
    assert receipt(untouched, 3, LIMIT, touched=False) == ""
    assert "matched nothing" in receipt(untouched, 3, LIMIT, touched=True)
    assert receipt(None, 3, LIMIT, True) == ""
