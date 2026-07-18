import { Text } from '@fluentui/react-components';
import { DocumentData20Regular } from '@fluentui/react-icons';
import type { Citation } from '../types';

interface CitationsProps {
  citations: Citation[];
}

export function Citations({ citations }: CitationsProps) {
  return (
    <details className="citations" open>
      <summary><DocumentData20Regular /><span>{citations.length} grounded source{citations.length === 1 ? '' : 's'}</span></summary>
      <ol>
        {citations.map((citation) => (
          <li key={`${citation.documentId}-${citation.section}`}>
            <div><span className="citation-number">{citation.documentId}</span><Text weight="semibold">{citation.title}</Text></div>
            <Text size={200}>{citation.section}</Text>
            <blockquote>{citation.excerpt}</blockquote>
            <span className="classification-label">Synthetic internal</span>
          </li>
        ))}
      </ol>
    </details>
  );
}
