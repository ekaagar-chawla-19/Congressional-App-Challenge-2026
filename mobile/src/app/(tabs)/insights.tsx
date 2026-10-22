import { ChartColumn } from '@/icons';
import { Empty, Screen, T } from '@/ui';
import { isServer, useSession } from '@/session';
import Insights from '@/Insights';

// Forest-level analysis tab. Sections and map areas open the same view as a pushed screen (/insights).
export default function InsightsTab() {
  useSession((s) => s.mode); // re-render on sign-in changes
  if (!isServer()) {
    return (
      <Screen tabbed>
        <T v="display">Insights</T>
        <Empty icon={ChartColumn} title="Needs the server" body="Forest-wide analysis, sections and disease trends come from the HemlockID server. In phone-only mode, each tree's page has its own diagnosis, sensor history and next steps, and the map shows health and sensor layers." />
      </Screen>
    );
  }
  return <Insights scope={{ kind: 'forest' }} tabbed />;
}
