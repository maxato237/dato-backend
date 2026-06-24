import io

# Plus petit PNG valide (1×1 px transparent).
_PNG_1PX = bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000a49444154789c6360000002000154a24f9c0000000049454e44ae426082'
)


def _auth_headers(client):
    r = client.post('/api/auth/register', json={
        'phone': '+237674000111', 'name': 'Upl', 'password': 'password123'
    })
    otp = r.get_json()['data']['dev_otp']
    tokens = client.post('/api/auth/verify-otp', json={
        'phone': '+237674000111', 'code': otp, 'purpose': 'registration'
    }).get_json()['data']
    return {'Authorization': f'Bearer {tokens["access_token"]}'}


class TestUploads:
    def test_upload_requires_auth(self, client):
        r = client.post('/api/uploads')
        assert r.status_code == 401

    def test_upload_image_success(self, client):
        headers = _auth_headers(client)
        data = {'file': (io.BytesIO(_PNG_1PX), 'logo.png')}
        r = client.post('/api/uploads', data=data,
                        content_type='multipart/form-data', headers=headers)
        assert r.status_code == 200
        body = r.get_json()['data']
        assert body['url'].endswith(body['filename'])
        assert '/uploads/' in body['url']

        # Le fichier est ensuite servi publiquement.
        served = client.get('/uploads/' + body['filename'])
        assert served.status_code == 200

    def test_upload_rejects_bad_extension(self, client):
        headers = _auth_headers(client)
        data = {'file': (io.BytesIO(b'not an image'), 'malware.exe')}
        r = client.post('/api/uploads', data=data,
                        content_type='multipart/form-data', headers=headers)
        assert r.status_code == 400

    def test_upload_missing_file(self, client):
        headers = _auth_headers(client)
        r = client.post('/api/uploads', data={},
                        content_type='multipart/form-data', headers=headers)
        assert r.status_code == 400


class TestSupabaseStorage:
    def test_upload_uses_supabase_when_configured(self, app, monkeypatch):
        """Quand Supabase est configuré, save_image poste vers le bucket et
        retourne l'URL publique (sans toucher au disque local)."""
        import app.services.storage_service as ss

        monkeypatch.setitem(app.config, 'SUPABASE_URL', 'https://proj.supabase.co')
        monkeypatch.setitem(app.config, 'SUPABASE_SERVICE_ROLE_KEY', 'svc-key')
        monkeypatch.setitem(app.config, 'SUPABASE_STORAGE_BUCKET', 'DATO_PROFIL_PDP_PDC')

        captured = {}

        class _FakeResp:
            status_code = 200
            text = ''

        def _fake_post(url, data=None, headers=None, timeout=None):
            captured['url'] = url
            captured['headers'] = headers
            captured['data'] = data
            return _FakeResp()

        monkeypatch.setattr(ss.requests, 'post', _fake_post)

        class _FakeFile:
            mimetype = 'image/png'

            def read(self):
                return b'\x89PNG-bytes'

        with app.app_context():
            url = ss.save_image(_FakeFile(), 'png')

        assert url.startswith(
            'https://proj.supabase.co/storage/v1/object/public/DATO_PROFIL_PDP_PDC/'
        )
        assert url.endswith('.png')
        assert captured['headers']['Authorization'] == 'Bearer svc-key'
        assert captured['headers']['apikey'] == 'svc-key'
        assert captured['data'] == b'\x89PNG-bytes'
        # L'URL d'upload (privée) cible le bon bucket.
        assert '/storage/v1/object/DATO_PROFIL_PDP_PDC/' in captured['url']

    def test_upload_supabase_failure_raises(self, app, monkeypatch):
        import app.services.storage_service as ss
        from app.utils.errors import ApiError

        monkeypatch.setitem(app.config, 'SUPABASE_URL', 'https://proj.supabase.co')
        monkeypatch.setitem(app.config, 'SUPABASE_SERVICE_ROLE_KEY', 'svc-key')

        class _FakeResp:
            status_code = 400
            text = 'bad request'

        monkeypatch.setattr(ss.requests, 'post', lambda *a, **k: _FakeResp())

        class _FakeFile:
            mimetype = 'image/png'

            def read(self):
                return b'x'

        with app.app_context():
            try:
                ss.save_image(_FakeFile(), 'png')
                assert False, 'aurait dû lever ApiError'
            except ApiError as e:
                assert e.status_code == 502


class TestCompanyImageFields:
    def test_company_accepts_image_fields(self, client):
        headers = _auth_headers(client)
        payload = {
            'name': 'MILLENAIRE DECOR',
            'activity': 'Menuiserie',
            'address': 'BP 705 YDE',
            'city': 'Yaoundé',
            'phones': ['674702037'],
            'currency': 'FCFA',
            'logo_url': 'http://x/uploads/logo.png',
            'location': 'Situé à NKOLFOULOU (carrefour ENIET de SOA)',
            'template_docx_url': 'http://x/uploads/template.docx',
        }
        r = client.post('/api/company', json=payload, headers=headers)
        assert r.status_code == 201
        data = r.get_json()['data']
        assert data['address'] == 'BP 705 YDE'
        assert data['logo_url'] == 'http://x/uploads/logo.png'
        assert data['location'].startswith('Situé à NKOLFOULOU')
        assert data['template_docx_url'] == 'http://x/uploads/template.docx'

    def test_company_update_image_fields(self, client):
        headers = _auth_headers(client)
        client.post('/api/company', json={'name': 'X', 'phones': []}, headers=headers)
        r = client.put('/api/company', json={
            'name': 'X', 'location': 'Yaoundé centre', 'logo_url': 'http://x/uploads/l.png',
        }, headers=headers)
        assert r.status_code == 200
        data = r.get_json()['data']
        assert data['location'] == 'Yaoundé centre'
        assert data['logo_url'] == 'http://x/uploads/l.png'
