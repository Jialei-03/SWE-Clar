export function requireConfiguredEndpoint(config) {
  if (typeof config.base_url !== 'string' || !config.base_url.trim()) {
    throw new Error('Configure base_url explicitly for a model absent from the provider catalog');
  }
  return config.base_url;
}
