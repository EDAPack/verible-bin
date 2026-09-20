// Minimal SystemVerilog fixture for the verible-bin repack smoke test.
//
// Deliberately written to be BOTH lint-clean under Verible's default rule set
// AND a fixed point of verible-verilog-format, so the smoke test can assert
// "lint says nothing" and "formatting is a no-op" without a golden file that
// drifts every time upstream tweaks a style rule. If a future Verible release
// changes either, that is a real signal about the release, not test rot --
// update this file deliberately rather than loosening the assertions.
module smoke #(
    parameter int Width = 8
) (
    input logic clk,
    input logic rst_n,
    input logic [Width-1:0] d,
    output logic [Width-1:0] q
);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      q <= '0;
    end else begin
      q <= d;
    end
  end

endmodule : smoke
