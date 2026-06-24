import pytest


def _setup_user_with_company(client):
    """Inscrit un utilisateur, le vérifie et crée son entreprise. Retourne les headers."""
    r = client.post('/api/auth/register', json={
        'phone': '+237674000099', 'name': 'Test', 'password': 'password123'
    })
    otp = r.get_json()['data']['dev_otp']
    tokens = client.post('/api/auth/verify-otp', json={
        'phone': '+237674000099', 'code': otp, 'purpose': 'registration'
    }).get_json()['data']
    headers = {'Authorization': f'Bearer {tokens["access_token"]}'}

    client.post('/api/company', json={
        'name': 'Ma Boîte', 'currency': 'FCFA', 'phones': ['+237674000099']
    }, headers=headers)
    return headers


def _quote_payload(**kwargs):
    base = {
        'title': 'Devis test',
        'validity_days': 30,
        'items': [
            {'description': 'Prestation A', 'quantity': 2, 'unit_price': 50000, 'unit': 'heure'},
        ],
    }
    base.update(kwargs)
    return base


class TestQuoteCrud:
    def test_create_quote(self, client):
        headers = _setup_user_with_company(client)
        r = client.post('/api/quotes', json=_quote_payload(), headers=headers)
        assert r.status_code == 201
        data = r.get_json()['data']
        assert data['number'].startswith('DEV-')
        assert data['status'] == 'draft'
        assert len(data['items']) == 1
        assert data['total'] == 100000.0

    def test_quote_number_increments(self, client):
        headers = _setup_user_with_company(client)
        r1 = client.post('/api/quotes', json=_quote_payload(), headers=headers)
        r2 = client.post('/api/quotes', json=_quote_payload(), headers=headers)
        n1 = r1.get_json()['data']['number']
        n2 = r2.get_json()['data']['number']
        assert n1 != n2

    def test_list_quotes(self, client):
        headers = _setup_user_with_company(client)
        client.post('/api/quotes', json=_quote_payload(), headers=headers)
        client.post('/api/quotes', json=_quote_payload(title='Devis 2'), headers=headers)
        r = client.get('/api/quotes', headers=headers)
        assert r.status_code == 200
        assert len(r.get_json()['data']) == 2

    def test_filter_by_status(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        client.patch(f'/api/quotes/{q["id"]}/status', json={'status': 'sent'}, headers=headers)
        client.post('/api/quotes', json=_quote_payload(title='Draft'), headers=headers)

        r = client.get('/api/quotes?status=sent', headers=headers)
        assert len(r.get_json()['data']) == 1
        r2 = client.get('/api/quotes?status=draft', headers=headers)
        assert len(r2.get_json()['data']) == 1

    def test_update_quote(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        r = client.put(f'/api/quotes/{q["id"]}', json={'title': 'Titre modifié'}, headers=headers)
        assert r.status_code == 200
        assert r.get_json()['data']['title'] == 'Titre modifié'

    def test_cannot_update_accepted_quote(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        client.patch(f'/api/quotes/{q["id"]}/status', json={'status': 'accepted'}, headers=headers)
        r = client.put(f'/api/quotes/{q["id"]}', json={'title': 'Tentative'}, headers=headers)
        assert r.status_code == 409

    def test_delete_quote(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        r = client.delete(f'/api/quotes/{q["id"]}', headers=headers)
        assert r.status_code == 204

    def test_duplicate_quote(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        r = client.post(f'/api/quotes/{q["id"]}/duplicate', headers=headers)
        assert r.status_code == 201
        copy = r.get_json()['data']
        assert copy['number'] != q['number']
        assert 'Copie' in copy['title']
        assert copy['total'] == q['total']


class TestPublicShare:
    def test_public_view_accessible_without_auth(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        # Pas de header Authorization → la vue publique reste accessible.
        r = client.get(f'/p/{q["share_token"]}')
        assert r.status_code == 200
        data = r.get_json()['data']
        assert data['number'] == q['number']
        assert 'company' in data

    def test_public_view_returns_document_json_snapshot(self, client):
        headers = _setup_user_with_company(client)
        snapshot = {
            'sections': [{'title': 'Matériel', 'lines': [{'designation': 'Planche', 'qty': 2, 'pu': 1000}]}],
            'rubriques': [{'label': 'Usinage', 'lines': [{'mode': 'forfait', 'amount': 5000}]}],
            'grandTotal': 7000,
        }
        q = client.post('/api/quotes', json=_quote_payload(document_json=snapshot),
                        headers=headers).get_json()['data']
        assert q['document_json'] == snapshot
        r = client.get(f'/p/{q["share_token"]}')
        assert r.get_json()['data']['document_json'] == snapshot

    def test_unknown_token_returns_404(self, client):
        import uuid
        assert client.get(f'/p/{uuid.uuid4()}').status_code == 404

    def test_enable_share_returns_public_url(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        r = client.post(f'/api/quotes/{q["id"]}/share', headers=headers)
        assert r.status_code == 200
        data = r.get_json()['data']
        assert data['share_enabled'] is True
        assert f'/p/{q["share_token"]}' in data['public_url']

    def test_revoke_makes_public_view_404(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        token = q['share_token']
        assert client.get(f'/p/{token}').status_code == 200
        r = client.delete(f'/api/quotes/{q["id"]}/share', headers=headers)
        assert r.status_code == 200
        assert r.get_json()['data']['share_enabled'] is False
        assert client.get(f'/p/{token}').status_code == 404

    def test_regenerate_invalidates_old_link(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        old = q['share_token']
        new = client.post(f'/api/quotes/{q["id"]}/share/regenerate',
                          headers=headers).get_json()['data']['share_token']
        assert new != old
        assert client.get(f'/p/{old}').status_code == 404
        assert client.get(f'/p/{new}').status_code == 200


class TestSyncIdempotency:
    def test_create_honours_client_id_and_number(self, client):
        import uuid
        headers = _setup_user_with_company(client)
        qid = str(uuid.uuid4())
        r = client.post('/api/quotes', json=_quote_payload(id=qid, number='DEV-2026-042'),
                        headers=headers)
        assert r.status_code == 201
        data = r.get_json()['data']
        assert data['id'] == qid
        assert data['number'] == 'DEV-2026-042'

    def test_replayed_create_is_idempotent(self, client):
        import uuid
        headers = _setup_user_with_company(client)
        qid = str(uuid.uuid4())
        payload = _quote_payload(id=qid)
        r1 = client.post('/api/quotes', json=payload, headers=headers)
        r2 = client.post('/api/quotes', json=payload, headers=headers)
        assert r1.status_code == 201
        assert r2.status_code == 200  # rejeu de la file de sync → pas de doublon
        assert r2.get_json()['data']['id'] == qid
        lst = client.get('/api/quotes', headers=headers).get_json()['data']
        assert len([x for x in lst if x['id'] == qid]) == 1

    def test_delete_is_idempotent(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        assert client.delete(f'/api/quotes/{q["id"]}', headers=headers).status_code == 204
        assert client.delete(f'/api/quotes/{q["id"]}', headers=headers).status_code == 204


class TestTotals:
    def test_tax_computed_correctly(self, client):
        headers = _setup_user_with_company(client)
        r = client.post('/api/quotes', json=_quote_payload(
            tax_rate=19.25,
            items=[{'description': 'Service', 'quantity': 1, 'unit_price': 100000}],
        ), headers=headers)
        data = r.get_json()['data']
        assert data['subtotal'] == 100000.0
        assert abs(data['tax_amount'] - 19250.0) < 0.01
        assert abs(data['total'] - 119250.0) < 0.01
