import { useEffect, useMemo, useState } from 'react';
import { Button, Field, Input, Select, Text } from '@fluentui/react-components';
import { CheckmarkCircle20Regular, Clipboard20Regular, DocumentData20Regular, Search20Regular } from '@fluentui/react-icons';
import { formatDateTime, shortHash } from '../format';
import type { AppView, ConsoleSnapshot, EvidenceItem } from '../types';
import { DetailPanel } from '../components/DetailPanel';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';

interface EvidenceScreenProps {
  data: ConsoleSnapshot;
  publicMode: boolean;
  focusId?: string;
  onNavigate: (view: AppView, id?: string) => void;
  onCommand: (message: string) => void;
}

export function EvidenceScreen({ data, publicMode, focusId, onNavigate, onCommand }: EvidenceScreenProps) {
  const [search, setSearch] = useState('');
  const [source, setSource] = useState('ALL');
  const [freshness, setFreshness] = useState('ALL');
  const [selected, setSelected] = useState<EvidenceItem>();

  useEffect(() => {
    if (focusId) setSelected(data.evidence.find((item) => item.id === focusId));
  }, [data.evidence, focusId]);

  const sources = [...new Set(data.evidence.map((item) => item.source))];
  const filtered = useMemo(() => data.evidence.filter((item) => {
    const needle = search.trim().toLowerCase();
    const matchesText = !needle || `${item.id} ${item.source} ${item.summary} ${item.controlIds.join(' ')}`.toLowerCase().includes(needle);
    return matchesText && (source === 'ALL' || item.source === source) && (freshness === 'ALL' || item.freshness === freshness);
  }), [data.evidence, freshness, search, source]);

  const copyHash = async (hash: string) => {
    try {
      await navigator.clipboard?.writeText(hash);
      onCommand('Evidence hash copied. Verify it against the signed run manifest, not the UI alone.');
    } catch {
      onCommand('Clipboard access was denied. Select the hash in the evidence metadata to copy it manually.');
    }
  };

  return (
    <div className="screen-stack">
      <PageHeader eyebrow="Provenance & integrity" title="Evidence" description="Collected metadata, freshness, redaction, and cryptographic references for the selected assessment run." />

      <div className="evidence-boundary" role="note">
        <DocumentData20Regular />
        <Text><strong>{publicMode ? 'Sanitized evidence metadata only.' : 'Private evidence access is role-scoped.'}</strong> Raw payloads are never embedded in the browser; hashes resolve through the signed run manifest.</Text>
      </div>

      <div className="filter-bar" role="search">
        <Field label="Search evidence" className="search-field"><Input value={search} onChange={(_, value) => setSearch(value.value)} contentBefore={<Search20Regular />} placeholder="Source, control, ID, or summary" /></Field>
        <Field label="Source"><Select value={source} onChange={(_, value) => setSource(value.value)}><option value="ALL">All sources</option>{sources.map((item) => <option key={item}>{item}</option>)}</Select></Field>
        <Field label="Freshness"><Select value={freshness} onChange={(_, value) => setFreshness(value.value)}><option value="ALL">All freshness</option><option>CURRENT</option><option>STALE</option><option>UNAVAILABLE</option></Select></Field>
        <Text size={200} className="filter-count">{filtered.length} artifacts</Text>
      </div>

      <div className={`master-detail ${selected ? 'detail-open' : ''}`}>
        <section className="table-card" aria-label="Evidence items">
          <div className="table-scroll">
            <table className="data-table evidence-table">
              <thead><tr><th>Evidence</th><th>Source / method</th><th>Captured</th><th>Scope</th><th>Classification</th><th>Redaction</th><th>Hash</th><th>Controls</th></tr></thead>
              <tbody>
                {filtered.map((item) => (
                  <tr key={item.id} className={selected?.id === item.id ? 'selected-row' : undefined}>
                    <td><button type="button" className="table-primary-link" onClick={() => setSelected(item)}><strong>{item.id}</strong><span>{item.summary}</span></button></td>
                    <td><strong>{item.source}</strong><span className="cell-secondary">{item.method} · {item.collectorVersion}</span></td>
                    <td>{formatDateTime(item.capturedAt)}<span className="cell-secondary"><StatusBadge value={item.freshness} subtle /></span></td>
                    <td>{item.resourceScope}</td>
                    <td><StatusBadge value={item.sensitivity} subtle /></td>
                    <td><StatusBadge value={item.redaction} subtle /></td>
                    <td><code>{shortHash(item.hash)}</code></td>
                    <td>{item.controlIds.map((id) => <button className="inline-link" type="button" key={id} onClick={() => onNavigate('controls', id)}>{id}</button>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!filtered.length ? <div className="inline-empty"><Search20Regular /><Text>No evidence matches these filters.</Text><Button appearance="subtle" onClick={() => { setSearch(''); setSource('ALL'); setFreshness('ALL'); }}>Clear filters</Button></div> : null}
        </section>

        {selected ? (
          <DetailPanel title={selected.id} subtitle={`${selected.source} · ${selected.mediaType}`} onClose={() => setSelected(undefined)} actions={<Button appearance="secondary" icon={<Clipboard20Regular />} onClick={() => void copyHash(selected.hash)}>Copy SHA-256</Button>}>
            <div className="detail-status-row"><StatusBadge value={selected.freshness} /><StatusBadge value={selected.sensitivity} subtle /><StatusBadge value={selected.redaction} subtle /></div>
            <section className="workpaper-section"><Text weight="semibold">Sanitized summary</Text><p>{selected.summary}</p></section>
            <dl className="metadata-list">
              <div><dt>Collection method</dt><dd>{selected.method}</dd></div>
              <div><dt>Query / API digest</dt><dd><code>{selected.queryDigest}</code></dd></div>
              <div><dt>Collector version</dt><dd><code>{selected.collectorVersion}</code></dd></div>
              <div><dt>Capture time</dt><dd>{formatDateTime(selected.capturedAt)}</dd></div>
              <div><dt>Resource scope</dt><dd>{selected.resourceScope}</dd></div>
              <div><dt>Blob version</dt><dd><code>{selected.blobVersion}</code></dd></div>
              <div><dt>SHA-256</dt><dd className="break-code"><code>{selected.hash}</code></dd></div>
            </dl>
            <section className="workpaper-section"><Text weight="semibold">Linked objectives</Text><div className="chip-list">{selected.controlIds.map((id) => <Button key={id} appearance="outline" size="small" onClick={() => onNavigate('controls', id)}>{id}</Button>)}</div></section>
            <div className="integrity-note"><CheckmarkCircle20Regular /><Text size={200}>Metadata is traceable to a versioned blob and signed run manifest. This is described as tamper-evident, not tamper-proof.</Text></div>
          </DetailPanel>
        ) : null}
      </div>
    </div>
  );
}
