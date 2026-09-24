import { BusinessProvider } from "@/lib/business";
import { Shell } from "@/components/Shell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <BusinessProvider>
      <Shell>{children}</Shell>
    </BusinessProvider>
  );
}
