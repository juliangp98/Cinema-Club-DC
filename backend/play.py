"""What there is to play in a club today (R10 Play): one summary for the
feed's rail (desktop) and chip strip (phones), the Club page's games row,
the Play page's header and Discord's /play — today's trivia, this month's
bingo, polls waiting for your vote, and your kernels."""


def summary(group, user):
    """{trivia, bingo, polls, kernels, todo} for `user` in `group`. trivia /
    bingo are None when the club has them off."""
    import bingo
    import kernels
    import trivia
    from app import open_polls
    out = {'trivia': None, 'bingo': None}

    t = trivia.today_for(group, user)
    if t.get('enabled'):
        q = t.get('question')
        out['trivia'] = {'daily': t['daily'], 'anytime': t['anytime'],
                         'to_answer': bool(q and not q.get('mine')), 'waiting': bool(t.get('waiting')),
                         'answered': bool(q and q.get('mine')), 'correct': bool(q and (q.get('mine') or {}).get('correct'))}

    if group.bingo_enabled:
        card = bingo.card_for(group)
        p = bingo.progress(card, user.id)
        out['bingo'] = {'month_label': bingo.month_bounds(card.month)[0].strftime('%B'), 'filled': p['filled'],
                        'line': bool(p['line_at']), 'full': bool(p['full_at']),
                        'cells': [i == bingo.FREE or bool(cell and cell[2]) for i, cell in enumerate(p['squares'])]}

    polls = out['polls'] = open_polls(group.id, user.id, 5)

    out['challenges'] = None
    if group.challenges_enabled:                      # invites waiting for you, and challenges where it's your turn
        import challenges
        import tournaments
        mine = [c for c in challenges.visible(group.id, user.id) if c.status == 'open' and challenges.player(c, user.id)]

        def brief(c):                                 # a tournament's match: "🏆 Winners' round 1"
            t = challenges._tournament_of(c)
            others = [p.user.name for p in c.players if p.user_id != user.id and p.user
                      and p.status not in ('declined', 'expired')]
            return {'id': c.id, 'game': f"🏆 {t['match']}" if t else ' '.join(challenges.label(c.kind)),
                    'by': c.creator.name if c.creator else None,
                    'against': ', '.join(others[:3]) + (f' and {len(others) - 3} more' if len(others) > 3 else '')}
        out['challenges'] = {'invites': [brief(c) for c in mine if challenges.player(c, user.id).status == 'invited'],
                             'your_turn': [brief(c) for c in mine if challenges.player(c, user.id).status == 'accepted'],
                             'tournaments': [{'id': t.id, 'title': tournaments.title(t), 'by': t.creator.name if t.creator else None}
                                             for t in tournaments.visible(group.id, user.id) if t.status == 'open'
                                             and (p := tournaments.player(t, user.id)) and p.status == 'invited']}

    k = kernels.breakdown(user.id, group.id)
    out['kernels'] = {'kernels': k['kernels'], **{part: k[part] for part in kernels.PARTS},
                      'allowance': kernels.allowance(user.id), 'today': kernels.left_today(user, group)}
    out['todo'] = (int(bool(out['trivia'] and out['trivia']['to_answer']))
                   + sum(1 for p in polls if not p['you_voted'])
                   + (sum(len(out['challenges'][k]) for k in ('invites', 'your_turn', 'tournaments')) if out['challenges'] else 0))
    return out
