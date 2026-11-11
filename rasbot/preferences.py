"""Platform defaults applied only when creating a new engine session."""
import json


def default_model(store):
    path = store.root / 'preferences.json'
    return json.loads(path.read_text(encoding='utf-8')).get('model') if path.exists() else None


def evolution_model(store, client, requested=None):
    """Resolve follow-OpenCode once, without changing its global configuration."""
    selected = requested if requested is not None else default_model(store)
    if selected is not None:
        if (not isinstance(selected, dict) or set(selected) != {'id', 'providerID'}
                or not all(isinstance(v, str) and v.strip() for v in selected.values())):
            raise ValueError('模型设置无效，请在平台设置中重新选择模型。')
        return dict(selected)
    try:
        configs = client.request('GET', '/api/config')
        choices = set()
        if isinstance(configs, list):
            for config in configs:
                info = config.get('info', {}) if isinstance(config, dict) else {}
                model = info.get('model') if isinstance(info, dict) else None
                if isinstance(model, dict):
                    provider, identity = model.get('providerID'), model.get('model') or model.get('id')
                    if isinstance(provider, str) and provider and isinstance(identity, str) and identity:
                        choices.add((provider, identity))
        if len(choices) != 1:
            raise ValueError('无法确定 OpenCode 的默认模型，请在 OpenCode 中设置默认模型，或在平台设置中选择具体模型后重试。')
        provider, identity = choices.pop()
        if not any(m['providerID'] == provider and m['id'] == identity for m in models(client)):
            raise ValueError('OpenCode 默认模型当前不可用，请检查供应商连接，或在平台设置中选择其他模型。')
        return {'providerID': provider, 'id': identity}
    except RuntimeError as error:
        raise ValueError('无法读取 OpenCode 默认模型，请在平台设置中检查连接后重试。') from error


def models(client):
    return [{'id': m['id'], 'providerID': m['providerID'],
             'name': m.get('name') or m['id']}
            for m in client.request('GET', '/api/model')['data']
            if m.get('enabled') and m.get('status') != 'deprecated'
            and m.get('type') in (None, 'chat')]


def save_model(store, client, model):
    if model is not None:
        if not isinstance(model, dict) or set(model) != {'id', 'providerID'}:
            raise ValueError('Invalid model selection')
        if not any(m['id'] == model['id'] and m['providerID'] == model['providerID']
                   for m in models(client)):
            raise ValueError('Selected model is unavailable')
    path = store.root / 'preferences.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({'model': model}), encoding='utf-8')
    temp.replace(path)
    return {'model': model}


def apply_model(store, client, session_id):
    model = default_model(store)
    if model:
        client.request('POST', client.session_path(session_id) + '/model', {'model': model})
    return model
