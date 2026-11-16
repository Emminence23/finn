import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { TabBar } from "@/components/TabBar";
import { Gate } from "@/components/Gate";
import { WakeNote } from "@/components/WakeNote";
import { OfflineNote } from "@/components/OfflineNote";
import { ServiceWorker } from "@/components/ServiceWorker";
import { Tour } from "@/components/Tour";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "FINN",
  description: "Your morning brief: what changed in your portfolio, and who you know who can explain it.",
  appleWebApp: { capable: true, title: "FINN", statusBarStyle: "default" },
  icons: { apple: "/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f5f1" },
    { media: "(prefers-color-scheme: dark)", color: "#121211" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} antialiased`}>
        <ServiceWorker />
        <OfflineNote />
        <WakeNote />
        <Gate>
          <div className="mx-auto min-h-dvh max-w-xl pb-[calc(76px+env(safe-area-inset-bottom))]">
            {children}
          </div>
          <TabBar />
          <Tour />
        </Gate>
      </body>
    </html>
  );
}
