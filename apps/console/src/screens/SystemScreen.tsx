import { Text } from '@fluentui/react-components';
import { LockClosed20Regular, Organization24Regular, PersonLock24Regular } from '@fluentui/react-icons';
import type { ConsoleSnapshot } from '../types';
import { PageHeader } from '../components/PageHeader';
import { SectionCard } from '../components/SectionCard';
import { StatusBadge } from '../components/StatusBadge';

interface SystemScreenProps {
  data: ConsoleSnapshot;
}

export function SystemScreen({ data }: SystemScreenProps) {
  if (!data.system) {
    return (
      <div className="screen-stack">
        <PageHeader eyebrow="System security plan" title="System boundary" description="Architecture, inventory, identity, and trust-boundary data for the selected assessment." />
        <section className="evidence-boundary" role="status">
          <Organization24Regular />
          <Text><strong>System-boundary data is not included in this snapshot.</strong> The selected signed sample package and current read API do not provide a system record, so the Console does not substitute a diagram or inventory from fixture data.</Text>
        </section>
      </div>
    );
  }

  const system = data.system;
  const planes = Array.from(new Set(system.inventory.map((item) => item.plane))).map((plane) => ({
    plane,
    components: system.inventory.filter((item) => item.plane === plane),
  }));
  return (
    <div className="screen-stack">
      <PageHeader eyebrow={`System security plan · ${system.id} · schema ${system.schemaVersion}`} title={system.name} description="Architecture, data flows, trust boundaries, inventory, identities, classifications, exclusions, and shared-responsibility context." />

      <section className="boundary-summary">
        <div className="boundary-icon"><Organization24Regular /></div>
        <div><Text weight="semibold">Authorization boundary</Text><p>{system.boundary}</p></div>
        <StatusBadge value="INTERNAL" />
      </section>

      <SectionCard title="Assessed boundary architecture" description="Declared in the selected signed system record; live deployment presence and configuration require linked collector evidence.">
        <div className="architecture-flow runtime-architecture-flow" role="img" aria-label={system.boundary}>
          {planes.map(({ plane, components }) => (
            <div className="architecture-boundary" key={plane}>
              <span className="boundary-label">{plane}</span>
              {components.map((component) => <div className="architecture-node" key={component.name}><Organization24Regular /><strong>{component.name}</strong><span>{component.region} · {component.lifecycle}</span></div>)}
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Data flows" description="Runtime crossings are loaded from the selected signed package, including classification, protection, and retention context.">
        <div className="table-scroll"><table className="data-table"><thead><tr><th>Flow</th><th>Source → destination</th><th>Data</th><th>Class</th><th>Protection</th><th>Retention</th></tr></thead><tbody>{system.dataFlows.map((flow) => <tr key={flow.id}><td><strong>{flow.id}</strong></td><td>{flow.source} → {flow.destination}</td><td>{flow.data}</td><td><StatusBadge value={flow.classification} /></td><td>{flow.protection}</td><td>{flow.retention}</td></tr>)}</tbody></table></div>
      </SectionCard>

      <div className="two-column-grid system-grid">
        <SectionCard title="Trust boundaries" description="Every crossing has an independently scoped identity and evidence path.">
          <ol className="trust-list">{system.trustBoundaries.map((boundary, index) => <li key={boundary}><span>{index + 1}</span><Text>{boundary}</Text></li>)}</ol>
        </SectionCard>
        <SectionCard title="Data classification" description="The public dataset is a derived product, never a copy of the private evidence store.">
          <div className="classification-stack">
            {system.classifications.map((item) => <div key={item.classification}><StatusBadge value={item.classification} /><span><Text>{item.description}</Text><small>{item.handling}</small></span></div>)}
          </div>
          <p className="muted">{system.dataClassification}</p>
        </SectionCard>
      </div>

      <SectionCard title="Declared system inventory" description="Assessed design scope from the selected signed package, not an assertion that every component is currently deployed. Enterprise private-networking target state is documented separately.">
        <div className="table-scroll"><table className="data-table"><thead><tr><th>Component</th><th>Type</th><th>Plane</th><th>Region</th><th>Lifecycle</th></tr></thead><tbody>{system.inventory.map((item) => <tr key={item.name}><td><strong>{item.name}</strong></td><td>{item.type}</td><td>{item.plane}</td><td>{item.region}</td><td>{item.lifecycle}</td></tr>)}</tbody></table></div>
      </SectionCard>

      <SectionCard title="Workload identities" description="Separation limits evidence collection, application access, review decisions, and deployment authority.">
        <div className="identity-grid">{system.identities.map((identity) => <article key={identity.name}><PersonLock24Regular /><div><strong>{identity.name}</strong><Text>{identity.purpose}</Text><code>{identity.privilege}</code><small>{identity.authentication} · {identity.assignedScope}</small></div></article>)}</div>
      </SectionCard>

      <SectionCard title="Explicit exclusions" description="These limits are part of the selected package and prevent the assurance result from implying a broader claim.">
        <ul>{system.exclusions.map((exclusion) => <li key={exclusion}>{exclusion}</li>)}</ul>
      </SectionCard>

      <section className="responsibility-statement"><LockClosed20Regular /><div><Text weight="semibold">Shared responsibility and independence statement</Text><p>{system.sharedResponsibility}</p></div></section>
    </div>
  );
}
