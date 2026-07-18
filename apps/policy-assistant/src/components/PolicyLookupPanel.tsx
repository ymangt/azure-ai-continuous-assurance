import { useState } from 'react';
import { Button, Field, Input, Spinner, Text } from '@fluentui/react-components';
import { BookInformation20Regular, Search20Regular } from '@fluentui/react-icons';
import { assistantApi } from '../api/client';
import type { PolicyLookupResult } from '../types';

interface PolicyLookupPanelProps {
  replayMode: boolean;
}

export function PolicyLookupPanel({ replayMode }: PolicyLookupPanelProps) {
  const [query, setQuery] = useState('temporary administrator access');
  const [result, setResult] = useState<PolicyLookupResult>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();

  const lookup = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(undefined);
    try {
      setResult(await assistantApi.lookupPolicy(query.trim(), replayMode));
    } catch (lookupError) {
      setError(lookupError instanceof Error ? lookupError.message : 'Lookup failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <aside className="lookup-panel" aria-labelledby="lookup-title">
      <div className="panel-heading"><span><BookInformation20Regular /></span><div><Text id="lookup-title" weight="semibold">Policy lookup</Text><Text size={200}>Read-only trusted metadata</Text></div></div>
      <Field label="Owner, section, or approval requirement"><Input value={query} onChange={(_, data) => setQuery(data.value)} onKeyDown={(event) => { if (event.key === 'Enter') void lookup(); }} /></Field>
      <Button appearance="secondary" icon={loading ? <Spinner size="tiny" /> : <Search20Regular />} disabled={loading || !query.trim()} onClick={() => void lookup()}>Look up policy</Button>
      {error ? <div className="lookup-error" role="alert">{error}</div> : null}
      {result ? <div className="lookup-result" role="status"><div><span>{result.documentId}</span><strong>{result.section}</strong></div><dl><dt>Owner</dt><dd>{result.owner}</dd><dt>Approval</dt><dd>{result.approvalRequirement}</dd></dl><Text size={100}>Correlation <code>{result.correlationId}</code></Text></div> : null}
      <Text size={200} className="lookup-hint">This tool can retrieve metadata. It cannot create or approve anything.</Text>
    </aside>
  );
}
