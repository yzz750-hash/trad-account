import Link from "next/link";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[calc(100vh-4rem)]">
      <div className="w-64 border-r border-slate-200 bg-white p-6">
        <h2 className="text-lg font-bold mb-6">基础设置</h2>
        <nav className="flex flex-col gap-2 text-sm">
          <Link href="/settings/ledgers" className="px-3 py-2 rounded-md hover:bg-slate-100 transition-colors">
            账套管理
          </Link>
          <Link href="/settings/accounts" className="px-3 py-2 rounded-md hover:bg-slate-100 transition-colors">
            科目与期初
          </Link>
          <Link href="/settings/partners" className="px-3 py-2 rounded-md hover:bg-slate-100 transition-colors">
            客商档案
          </Link>
          <Link href="/settings/currencies" className="px-3 py-2 rounded-md hover:bg-slate-100 transition-colors">
            汇率管理
          </Link>
        </nav>
      </div>
      <div className="flex-1 bg-[#F8F9FA]">
        {children}
      </div>
    </div>
  );
}
