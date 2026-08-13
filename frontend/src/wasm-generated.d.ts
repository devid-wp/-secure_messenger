declare module '*wasm-generated/mls.js' {
  const initWasm: (...args: any[]) => Promise<any>
  const WasmMlsClient: any

  export default initWasm
  export { WasmMlsClient }
}
