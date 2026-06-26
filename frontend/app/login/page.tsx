import AuthForm from "@/components/AuthForm";

export const metadata = { title: "Sign in · ChordCoach" };

export default function LoginPage() {
  return (
    <main className="flex min-h-full items-center justify-center bg-bg-primary px-4 py-12">
      <AuthForm mode="signin" />
    </main>
  );
}
