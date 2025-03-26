(function () {
  // ======== Canvas Setup ========
  var canvas = document.querySelector("#canvas");
  var context = canvas.getContext("2d");
  canvas.width = 280;
  canvas.height = 280;

  // For drawing
  var Mouse = { x: 0, y: 0 };
  var lastMouse = { x: 0, y: 0 };
  context.fillStyle = "black";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.color = "white";
  context.lineWidth = 15;
  context.lineJoin = context.lineCap = "round";

  // Mouse events for drawing
  canvas.addEventListener(
    "mousemove",
    function (e) {
      lastMouse.x = Mouse.x;
      lastMouse.y = Mouse.y;
      Mouse.x = e.pageX - this.offsetLeft;
      Mouse.y = e.pageY - this.offsetTop;
    },
    false
  );
  canvas.addEventListener(
    "mousedown",
    function () {
      canvas.addEventListener("mousemove", onPaint, false);
    },
    false
  );
  canvas.addEventListener(
    "mouseup",
    function () {
      canvas.removeEventListener("mousemove", onPaint, false);
    },
    false
  );

  function onPaint() {
    context.lineWidth = context.lineWidth;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.strokeStyle = context.color;
    context.beginPath();
    context.moveTo(lastMouse.x, lastMouse.y);
    context.lineTo(Mouse.x, Mouse.y);
    context.closePath();
    context.stroke();
  }

  // ======== Canvas Buttons ========
  // Predict CPU / FPGA from the drawn canvas
  $("#predictButton").on("click", function () {
    var img = canvas.toDataURL("image/jpeg");
    predict(img, "cpu", "lenet");
  });

  $("#predictFpga").on("click", function () {
    var img = canvas.toDataURL("image/jpeg");
    predict(img, "fpga", "lenet");
  });

  $("#clearButton").on("click", function () {
    context.clearRect(0, 0, 280, 280);
    context.fillStyle = "black";
    context.fillRect(0, 0, canvas.width, canvas.height);
  });

  // Slider for line width
  var slider = document.getElementById("myRange");
  var output = document.getElementById("sliderValue");
  output.innerHTML = slider.value;
  slider.oninput = function () {
    output.innerHTML = this.value;
    context.lineWidth = $(this).val();
  };

  // ======== Camera Capture Logic ========
  // We'll store the captured image data in this variable
  let capturedData = null;

  // 1) Capture Image
  $("#captureButton").on("click", function () {
    $.ajax({
      type: "POST",
      url: "http://192.168.1.27:9090/capture", // Adjust IP if needed
      success: function (data) {
        capturedData = data.img; // store the base64 string
        // Show the image
        $("#capturedImg").attr("src", capturedData).show();
      },
      error: function (err) {
        console.error("Error capturing image", err);
      }
    });
  });

  // 2) Predict CPU on the captured image
  $("#predictCpuCaptured").on("click", function () {
    if (!capturedData) {
      alert("No image captured yet!");
      return;
    }
    predict(capturedData, "cpu", "lenet");
  });

  // 3) Predict FPGA on the captured image
  $("#predictFpgaCaptured").on("click", function () {
    if (!capturedData) {
      alert("No image captured yet!");
      return;
    }
    predict(capturedData, "fpga", "lenet");
  });

  // 4) Clear Captured Image
  $("#clearCapturedImage").on("click", function () {
    capturedData = null;
    $("#capturedImg").attr("src", "").hide();
  });

  // ======== Common Predict Function ========
  function predict(img, type = "cpu", net = "lenet") {
    $.ajax({
      type: "POST",
      url: "http://192.168.1.27:9090/predict",
      data: { img, type, net },
      success: function (data) {
        _update_table(data, type, net);
      },
      error: function (err) {
        console.error("Error in predict request:", err);
      }
    });
  }

  // ======== Update the Table ========
  function _update_table(data, type = "cpu", net = "lenet") {
    const res = data.res;
    const process_time = data.process_time;
    const distributions = _soft_max(res);

    // Update row: #lenetcpu or #lenetfpga
    const rowId = "#" + net + type; // e.g. "#lenetcpu" or "#lenetfpga"

    for (let i = 0; i < distributions.length; i++) {
      const element = _changeTwoDecimal(distributions[i]);
      $(rowId)
        .children("td")
        .eq(i + 1)
        .html(element);
    }
    // The last cell is Time Cost
    $(rowId)
      .children("td")
      .eq(distributions.length + 1)
      .html(_changeTwoDecimal(process_time));
  }

  // Convert raw scores to probabilities
  function _soft_max(arr) {
    let _total = 0;
    // Scale down by 100 if your model outputs are 0-100
    for (let i = 0; i < arr.length; i++) {
      arr[i] = arr[i] / 100.0;
    }
    for (let i = 0; i < arr.length; i++) {
      _total += Math.exp(arr[i]);
    }
    for (let i = 0; i < arr.length; i++) {
      arr[i] = Math.exp(arr[i]) / _total;
    }
    return arr;
  }

  function _changeTwoDecimal(x) {
    var f_x = parseFloat(x);
    if (isNaN(f_x)) {
      alert("function:changeTwoDecimal->parameter error");
      return false;
    }
    return Math.round(f_x * 100) / 100;
  }
})();
