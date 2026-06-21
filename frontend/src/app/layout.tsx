import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "智能外贸财务系统",
  description: "智能外贸财务管理系统，支持多账套、凭证管理、固定资产折旧、外币重估、税务计算与销售提成。",
};

import TopNav from "@/components/TopNav";
import AIChat from "@/components/AIChat";
import AuthGuard from "@/components/AuthGuard";
import { LedgerProvider } from "@/context/LedgerContext";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-surface text-text-primary font-sans selection:bg-slate-200">
        <LedgerProvider>
          <AuthGuard>
            <TopNav />
            <main className="flex-1 pb-40">
              {children}
            </main>
            <AIChat />
          </AuthGuard>
        </LedgerProvider>
      </body>
    </html>
  );
}
