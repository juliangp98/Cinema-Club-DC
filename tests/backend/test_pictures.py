"""R6b: member and club pictures (photo / emoji / initials / Discord)."""
import io
import os

import pytest
from PIL import Image

from helpers import H, client, setup_db


def jpeg(w=800, h=600):
    """A photo with camera make and GPS location in its EXIF."""
    img = Image.new('RGB', (w, h), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = 'PhoneMaker'
    exif[0x8825] = {1: 'N', 2: (38.0, 53.0, 0.0), 3: 'W', 4: (77.0, 2.0, 0.0)}
    buf = io.BytesIO()
    img.save(buf, 'JPEG', exif=exif)
    return buf.getvalue()


@pytest.fixture
def people():
    """Ana (admin of Picture Club), Bo (member, with a Discord picture), a guest."""
    import media
    from app import app, db, migrate, User, Group, GroupMembership
    setup_db()
    with app.app_context():
        ana = User(email='ana@r6b.test', name='Ana', is_active=True)
        bo = User(email='bo@r6b.test', name='Bo', is_active=True, discord_user_id='6601',
                  avatar_url='https://cdn.discordapp.com/avatars/6601/a.png')
        guest = User(name='Guest', is_active=True, is_guest=True)
        db.session.add_all([ana, bo, guest])
        db.session.flush()
        g = Group(name='Picture Club', slug='picture-club', is_public=True)
        db.session.add(g)
        db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=g.id, role='admin', status='active'),
                            GroupMembership(user_id=bo.id, group_id=g.id, role='member', status='active')])
        db.session.commit()
        migrate()                                          # the backfill runs on every start
        ids = {'ana': ana.id, 'bo': bo.id, 'guest': guest.id, 'group': g.id, 'slug': g.slug}
        ids['media'] = media.media_dir(app.instance_path)
        ids['bo_discord'] = db.session.get(User, bo.id).discord_avatar_url
    return ids


def upload(c, data, path='/api/me/picture', name='p.jpg'):
    return c.post(path, data={'file': (io.BytesIO(data), name)}, content_type='multipart/form-data')


def me(c):
    return c.get('/api/auth/me').json['user']


def test_defaults_and_the_discord_backfill(people):
    assert people['bo_discord'] == 'https://cdn.discordapp.com/avatars/6601/a.png'      # remembered as Discord's
    assert me(client(people['ana']))['avatar_kind'] == 'initials' and me(client(people['bo']))['avatar_kind'] == 'discord'


def test_an_uploaded_photo_is_a_clean_square_webp(people):
    a = client(people['ana'])
    r = upload(a, jpeg())
    u = r.json['user']
    assert r.status_code == 200 and u['avatar_kind'] == 'photo' and u['avatar_url'].startswith('/api/media/')
    f = a.get(u['avatar_url'])
    img = Image.open(io.BytesIO(f.data))
    assert f.status_code == 200 and f.mimetype == 'image/webp' and img.size == (256, 256)
    assert 'immutable' in f.headers['Cache-Control']
    assert not img.getexif() and b'PhoneMaker' not in f.data                  # location and camera gone


def test_switching_kinds_deletes_the_old_photo(people):
    a = client(people['ana'])
    first = upload(a, jpeg()).json['user']['avatar_url']
    r = a.put('/api/me/picture', json={'kind': 'emoji', 'emoji': '🎬'})
    assert r.json['user']['avatar_emoji'] == '🎬' and r.json['user']['avatar_url'] is None
    assert not os.path.exists(os.path.join(people['media'], first.rsplit('/', 1)[1]))
    r = a.put('/api/me/picture', json={'kind': 'initials'})
    assert r.json['user']['avatar_kind'] == 'initials' and not r.json['user']['avatar_emoji']


def test_what_is_refused(people):
    a = client(people['ana'])
    assert a.put('/api/me/picture', json={'kind': 'emoji', 'emoji': 'abc'}).status_code == 400
    assert a.put('/api/me/picture', json={'kind': 'emoji', 'emoji': '🎬 hi'}).status_code == 400
    assert a.put('/api/me/picture', json={'kind': 'discord'}).status_code == 400          # no Discord picture
    assert upload(a, b'hello there', name='x.jpg').status_code == 400                    # not a picture
    r = upload(a, os.urandom(5 * 1024 * 1024 + 10), name='big.jpg')
    assert r.status_code in (400, 413) and 'MB' in r.json['error']
    gif = io.BytesIO()
    Image.new('P', (40, 40)).save(gif, 'GIF')
    assert upload(a, gif.getvalue(), name='a.gif').status_code == 200                    # GIFs: first frame


def test_guests_choose_an_emoji_but_dont_upload(people):
    g = client(people['guest'])
    assert upload(g, jpeg()).status_code == 403
    assert g.put('/api/me/picture', json={'kind': 'emoji', 'emoji': '🍿'}).status_code == 200


def test_discord_pictures(people):
    b = client(people['bo'])
    b.put('/api/me/picture', json={'kind': 'emoji', 'emoji': '🎞️'})
    seen_in_discord = lambda url: client().get('/api/internal/profile', headers=H,
                                               query_string={'discord_user_id': '6601', 'discord_avatar': url})
    seen_in_discord('https://cdn.discordapp.com/avatars/6601/new.png')
    u = me(b)
    assert u['avatar_emoji'] == '🎞️' and u['avatar_url'] is None and u['discord_avatar_url'].endswith('new.png')   # emoji stays
    assert b.put('/api/me/picture', json={'kind': 'discord'}).json['user']['avatar_url'].endswith('new.png')
    seen_in_discord('https://cdn.discordapp.com/avatars/6601/newer.png')
    assert me(b)['avatar_url'].endswith('newer.png')                                     # follows Discord from then on


def test_pictures_go_wherever_names_go(people):
    from app import app, Showtime
    a = client(people['ana'])
    with app.app_context():
        sid = Showtime.query.first().id
    a.post('/api/messages', json={'showtime_id': sid, 'group_id': people['group'], 'body': 'hi'})
    last = a.get('/api/messages', query_string={'showtime_id': sid, 'group_id': people['group']}).json[-1]
    assert 'avatar_url' in last['user'] and 'avatar_emoji' in last['user']
    assert all('avatar_url' in m['user'] and 'avatar_emoji' in m['user'] for m in a.get(f"/api/groups/{people['slug']}/members").json)


def test_the_club_picture(people):
    a, b, slug = client(people['ana']), client(people['bo']), people['slug']
    assert upload(b, jpeg(), path=f'/api/groups/{slug}/picture').status_code == 403      # members can't
    r = upload(a, jpeg(1200, 400), path=f'/api/groups/{slug}/picture')
    photo = r.json['photo_url']
    assert r.status_code == 200 and Image.open(io.BytesIO(a.get(photo).data)).size == (512, 512)
    assert a.put(f'/api/groups/{slug}', json={'short_name': '  Picture Club Society  '}).json['short_name'] == 'Picture Club'
    r = a.put(f'/api/groups/{slug}', json={'emoji': '🎥'})
    assert r.json['emoji'] == '🎥' and r.json['photo_url'] is None
    assert not os.path.exists(os.path.join(people['media'], photo.rsplit('/', 1)[1]))
    assert a.put(f'/api/groups/{slug}', json={'emoji': 'x'}).status_code == 400
    assert next(x for x in b.get('/api/groups').json if x['slug'] == slug)['emoji'] == '🎥'
    r = a.put(f'/api/groups/{slug}', json={'emoji': '', 'short_name': ''})
    assert r.json['emoji'] is None and r.json['short_name'] == ''


def test_upload_limits_and_safe_names(people):
    a = client(people['ana'])
    small = io.BytesIO()
    Image.new('RGB', (10, 10)).save(small, 'PNG')
    codes = [upload(a, small.getvalue(), name='s.png').status_code for _ in range(25)]
    assert 429 in codes and codes.count(200) <= 20
    assert a.get('/api/media/..%2Fcinemaclub.db').status_code == 404 and a.get('/api/media/abc.webp').status_code == 404
