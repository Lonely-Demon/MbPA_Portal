export default function Signup() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-paper">
      <div className="w-full max-w-lg bg-white rounded-lg shadow-lg p-8">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-harbour">Create Account</h1>
          <p className="text-slate text-sm mt-1">MbPA Building Permission Portal</p>
        </div>
        <p className="text-center text-slate text-sm">Registration form — coming soon.</p>
        <p className="mt-4 text-center text-sm">
          <a href="/login" className="text-teal hover:underline">
            Back to sign in
          </a>
        </p>
      </div>
    </div>
  );
}
