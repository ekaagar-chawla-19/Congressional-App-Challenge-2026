import Insights from '@/Insights';

// Forest-level analysis tab: from the server, or worked out on the phone in phone-only mode. Sections and map areas
// open the same view as a pushed screen (/insights).
export default function InsightsTab() {
  return <Insights scope={{ kind: 'forest' }} tabbed />;
}
