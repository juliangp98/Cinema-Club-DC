"""R6b: member and club pictures (photo / emoji / initials / Discord)."""
from helpers import H, client, Checks, WORK


def test_pictures():
    checks = Checks()
    check = checks.check
    import io, os, sys
    from PIL import Image
    from app import app, db, migrate, User, Group, GroupMembership, Message, Showtime, INTERNAL_API_TOKEN
    import media
    H = {'X-Internal-Token': INTERNAL_API_TOKEN}

    def jpeg(w=800, h=600, gps=True):
        img = Image.new('RGB', (w, h), (200, 30, 30))
        exif = Image.Exif()
        exif[0x010F] = 'PhoneMaker'                      # camera make
        if gps:
            exif[0x8825] = {1: 'N', 2: (38.0, 53.0, 0.0), 3: 'W', 4: (77.0, 2.0, 0.0)}
        buf = io.BytesIO(); img.save(buf, 'JPEG', exif=exif); return buf.getvalue()

    with app.app_context():
        db.create_all(); migrate()
        ana = User(email='ana@r6b.test', name='Ana', is_active=True)
        bo = User(email='bo@r6b.test', name='Bo', is_active=True, discord_user_id='6601',
                  avatar_url='https://cdn.discordapp.com/avatars/6601/a.png')
        guest = User(name='Guest', is_active=True, is_guest=True)
        db.session.add_all([ana, bo, guest]); db.session.flush()
        g = Group(name='Picture Club', slug='picture-club', is_public=True); db.session.add(g); db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=g.id, role='admin', status='active'),
                            GroupMembership(user_id=bo.id, group_id=g.id, role='member', status='active')])
        db.session.commit()
        migrate()                                         # the backfill runs on every start
        check('migration: an existing Discord picture is remembered as such',
              db.session.get(User, bo.id).discord_avatar_url == 'https://cdn.discordapp.com/avatars/6601/a.png')
        A, B, GU, G, SLUG = ana.id, bo.id, guest.id, g.id, g.slug
        MEDIA = media.media_dir(app.instance_path)

    def client(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    a, b, gu = client(A), client(B), client(GU)
    up = lambda c, data, path='/api/me/picture', name='p.jpg': c.post(path, data={'file': (io.BytesIO(data), name)},
                                                                       content_type='multipart/form-data')
    me = lambda c: c.get('/api/auth/me').json['user']

    print('--- your picture ---')
    check('defaults: initials, or your Discord picture if you have one', me(a)['avatar_kind'] == 'initials' and me(b)['avatar_kind'] == 'discord')
    r = up(a, jpeg())
    u = r.json['user'] if r.status_code == 200 else {}
    check('upload a photo', r.status_code == 200 and u['avatar_kind'] == 'photo' and u['avatar_url'].startswith('/api/media/'), r.json)
    f = a.get(u['avatar_url'])
    img = Image.open(io.BytesIO(f.data))
    check('served as a 256px square WebP, cached for good', f.status_code == 200 and f.mimetype == 'image/webp'
          and img.size == (256, 256) and 'immutable' in f.headers['Cache-Control'])
    check('location and camera details are gone', not img.getexif() and b'PhoneMaker' not in f.data)
    first = u['avatar_url']
    r = a.put('/api/me/picture', json={'kind': 'emoji', 'emoji': '🎬'})
    check('switch to an emoji', r.json['user']['avatar_emoji'] == '🎬' and r.json['user']['avatar_url'] is None)
    check('…the old photo file is deleted', not os.path.exists(os.path.join(MEDIA, first.rsplit('/', 1)[1])))
    check('text is not an emoji', a.put('/api/me/picture', json={'kind': 'emoji', 'emoji': 'abc'}).status_code == 400
          and a.put('/api/me/picture', json={'kind': 'emoji', 'emoji': '🎬 hi'}).status_code == 400)
    check('no Discord picture to use', a.put('/api/me/picture', json={'kind': 'discord'}).status_code == 400)
    r = a.put('/api/me/picture', json={'kind': 'initials'})
    check('back to initials', r.json['user']['avatar_kind'] == 'initials' and not r.json['user']['avatar_emoji'])
    check('not a picture', up(a, b'hello there', name='x.jpg').status_code == 400)
    big = os.urandom(5 * 1024 * 1024 + 10)
    r = up(a, big, name='big.jpg')
    check('over 5 MB is refused', r.status_code in (400, 413) and 'MB' in r.json['error'], (r.status_code, r.get_data()[:80]))
    gif = io.BytesIO(); Image.new('P', (40, 40)).save(gif, 'GIF')
    check('GIFs work (first frame)', up(a, gif.getvalue(), name='a.gif').status_code == 200)
    check('guests keep their profile before uploading', up(gu, jpeg()).status_code == 403)
    check('guests can still pick an emoji', gu.put('/api/me/picture', json={'kind': 'emoji', 'emoji': '🍿'}).status_code == 200)

    print('--- Discord pictures ---')
    b.put('/api/me/picture', json={'kind': 'emoji', 'emoji': '🎞️'})
    bot = app.test_client()
    bot.get('/api/internal/profile', query_string={'discord_user_id': '6601', 'discord_avatar': 'https://cdn.discordapp.com/avatars/6601/new.png'}, headers=H)
    u = me(b)
    check('a new Discord picture is remembered, but your emoji stays', u['avatar_emoji'] == '🎞️' and u['avatar_url'] is None
          and u['discord_avatar_url'].endswith('new.png'))
    r = b.put('/api/me/picture', json={'kind': 'discord'})
    check('"use my Discord picture"', r.json['user']['avatar_url'].endswith('new.png'))
    bot.get('/api/internal/profile', query_string={'discord_user_id': '6601', 'discord_avatar': 'https://cdn.discordapp.com/avatars/6601/newer.png'}, headers=H)
    check('…and it follows Discord from then on', me(b)['avatar_url'].endswith('newer.png'))

    print('--- pictures go wherever names go ---')
    with app.app_context():
        sid = Showtime.query.first().id
    a.post('/api/messages', json={'showtime_id': sid, 'group_id': G, 'body': 'hi'})
    msgs = a.get('/api/messages', query_string={'showtime_id': sid, 'group_id': G}).json
    check('comments carry the picture', 'avatar_url' in msgs[-1]['user'] and 'avatar_emoji' in msgs[-1]['user'])
    mem = a.get(f'/api/groups/{SLUG}/members').json
    check('member list too', all('avatar_url' in m['user'] and 'avatar_emoji' in m['user'] for m in mem))

    print('--- club picture ---')
    r = up(b, jpeg(), path=f'/api/groups/{SLUG}/picture')
    check('members can\'t change it', r.status_code == 403)
    r = up(a, jpeg(1200, 400), path=f'/api/groups/{SLUG}/picture')
    cp = r.json.get('photo_url') or ''
    check('admins upload it: a 512px square', r.status_code == 200 and Image.open(io.BytesIO(a.get(cp).data)).size == (512, 512))
    r = a.put(f'/api/groups/{SLUG}', json={'short_name': '  Picture Club Society  '})
    check('short name: trimmed to 12', r.json['short_name'] == 'Picture Club')
    r = a.put(f'/api/groups/{SLUG}', json={'emoji': '🎥'})
    check('an emoji replaces the photo (file removed)', r.json['emoji'] == '🎥' and r.json['photo_url'] is None
          and not os.path.exists(os.path.join(MEDIA, cp.rsplit('/', 1)[1])))
    check('bad emoji refused', a.put(f'/api/groups/{SLUG}', json={'emoji': 'x'}).status_code == 400)
    check('everyone sees it in their club list', next(x for x in b.get('/api/groups').json if x['slug'] == SLUG)['emoji'] == '🎥')
    r = a.put(f'/api/groups/{SLUG}', json={'emoji': '', 'short_name': ''})
    check('clear both', r.json['emoji'] is None and r.json['short_name'] == '')

    print('--- limits ---')
    small = io.BytesIO(); Image.new('RGB', (10, 10)).save(small, 'PNG')
    codes = [up(a, small.getvalue(), name='s.png').status_code for _ in range(25)]
    check('uploads are limited per hour', 429 in codes and codes.count(200) <= 20, codes)
    check('only real media names are served', a.get('/api/media/..%2Fcinemaclub.db').status_code == 404
          and a.get('/api/media/abc.webp').status_code == 404)
    checks.done()
