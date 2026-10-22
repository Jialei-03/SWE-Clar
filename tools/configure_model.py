"""Generate a credential-free configuration for all four experimental roles."""
import argparse
import json
from pathlib import Path

APIS = {'chat': 'openai-completions', 'responses': 'openai-responses', 'claude': 'anthropic-messages'}

def configuration(style, base_url, model, key_env='SWECLAR_API_KEY'):
    if not base_url.startswith('https://'):
        raise ValueError('Use an HTTPS model endpoint')
    profile = dict(label=model, provider='custom-provider', builtin_provider=False, api=APIS[style],
                   base_url=base_url.rstrip('/'), model=model, api_key_env=key_env,
                   reasoning=True, thinking='max', context_window=128000,
                   model_max_output_tokens=16384)
    if style == 'chat':
        profile['compat'] = dict(supportsDeveloperRole=False, supportsReasoningEffort=True,
                                 maxTokensField='max_tokens')
    result = {'experiment_version': 'smoke-test', 'candidate': dict(profile, profile_id='candidate')}
    for role in ['client', 'supervisor', 'judge']:
        result[role] = dict(api_style='pi', model=model, pi_profile=dict(profile, profile_id=role))
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api', choices=APIS, required=True)
    p.add_argument('--base-url', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--key-env', default='SWECLAR_API_KEY')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    data = configuration(args.api, args.base_url, args.model, args.key_env)
    with args.output.open('x') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print('Created configuration. Review provider limits before a paid run. No credential was saved.')

if __name__ == '__main__':
    main()
