package com.yourcompany.usi_sm_os_app_v1

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.os.CountDownTimer
import android.os.StrictMode
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import io.ktor.serialization.gson.*
import io.ktor.server.application.*
import io.ktor.server.engine.*
import io.ktor.server.netty.*
import io.ktor.server.plugins.contentnegotiation.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.*
import kotlin.concurrent.thread

data class AlertLog(val aisle: String, val items: String, val time: String)
data class ProductItem(
    val id: Int,
    val productId: String,
    val productName: String,
    val category: String,
    val stock: Int,
    val price: Double,
    val maxCapacity: Int,
    val reorderLevel: Int
)

data class PendingRestock(
    val barcode: String,
    val qty: Int,
    var countdownSec: Int,
    val productName: String
)

class MainActivity : AppCompatActivity() {

    private val CHANNEL_ID = "USI_NOTIFY_CHANNEL"
    private val alertList = mutableListOf<AlertLog>()
    private lateinit var adapter: AlertAdapter
    private lateinit var currentStatusTextView: TextView
    private lateinit var productList: RecyclerView
    private lateinit var productAdapter: ProductAdapter
    private val products = mutableListOf<ProductItem>()
    private var server: NettyApplicationEngine? = null

    // API server address
    // Emulator: 10.0.2.2 (Android AVD maps to Windows localhost)
    // Physical device Wi-Fi: your PC LAN IP, e.g. 192.168.10.64
    private val API_HOST = "192.168.10.64"
    private val API_PORT = 8520
    private val API_BASE = "http://".plus(API_HOST).plus(":").plus(API_PORT.toString())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.GINGERBREAD) {
            StrictMode.setThreadPolicy(StrictMode.ThreadPolicy.Builder().permitAll().build())
        }

        currentStatusTextView = findViewById(R.id.currentStatusTextView)
        val recyclerView = findViewById<RecyclerView>(R.id.recyclerView)
        productList = findViewById(R.id.productList)

        adapter = AlertAdapter(alertList)
        recyclerView.layoutManager = LinearLayoutManager(this).apply { stackFromEnd = true }
        recyclerView.adapter = adapter

        productAdapter = ProductAdapter(products) { product, action ->
            showQuantityDialog(product, action)
        }
        productList.layoutManager = LinearLayoutManager(this)
        productList.adapter = productAdapter

        productAdapter.setOnHarvestListener { product ->
            harvestRestock(product)
        }

        createNotificationChannel()
        startWebServer()
        loadProducts()
    }

    // ========== HTTP Requests ==========

    private fun httpGet(endpoint: String): String? {
        try {
            val url = URL(API_BASE + endpoint)
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "GET"
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            val code = conn.responseCode
            if (code != 200) return null
            val reader = BufferedReader(InputStreamReader(conn.inputStream, "utf-8"))
            val result = reader.readText()
            reader.close()
            return result
        } catch (e: Exception) {
            runOnUiThread { currentStatusTextView.text = "Connect failed: " + e.message }
            return null
        }
    }

    private fun httpPost(endpoint: String, jsonBody: String): String? {
        try {
            val url = URL(API_BASE + endpoint)
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.connectTimeout = 10000
            conn.readTimeout = 10000
            val writer = OutputStreamWriter(conn.outputStream, "utf-8")
            writer.write(jsonBody)
            writer.flush()
            writer.close()
            val code = conn.responseCode
            val reader = BufferedReader(InputStreamReader(
                if (code in 200..299) conn.inputStream else conn.errorStream, "utf-8"
            ))
            val result = reader.readText()
            reader.close()
            return result
        } catch (e: Exception) {
            runOnUiThread { showToast("API error: " + e.message) }
            return null
        }
    }

    private fun loadProducts() {
        currentStatusTextView.text = "Loading..."
        thread {
            try {
                val json = httpGet("/products") ?: run {
                    runOnUiThread { currentStatusTextView.text = "X Cannot connect (http://" + API_HOST + ":" + API_PORT + ")" }
                    return@thread
                }
                val jsonStr = json
                if (!jsonStr.contains(""products"")) {
                    runOnUiThread { currentStatusTextView.text = "X Invalid API response" }
                    return@thread
                }

                val list = mutableListOf<ProductItem>()
                val arrStart = jsonStr.indexOf("[", jsonStr.indexOf(""products""))
                val arrEnd = jsonStr.lastIndexOf("]")
                val itemsStr = jsonStr.substring(arrStart + 1, arrEnd)
                if (itemsStr.isNotBlank()) {
                    var idx = 0
                    while (true) {
                        val objStart = itemsStr.indexOf("{", idx)
                        if (objStart < 0) break
                        val objEnd = itemsStr.indexOf("}", objStart)
                        if (objEnd < 0) break
                        val obj = itemsStr.substring(objStart, objEnd + 1)
                        list.add(parseProductItem(obj))
                        idx = objEnd + 1
                    }
                }

                runOnUiThread {
                    products.clear()
                    products.addAll(list)
                    productAdapter.notifyDataSetChanged()
                    currentStatusTextView.text = list.size.toString() + " products (API: " + API_HOST + ":" + API_PORT + ")"
                }
            } catch (e: Exception) {
                runOnUiThread {
                    currentStatusTextView.text = "X Load failed: " + e.message
                }
            }
        }
    }

    private fun parseProductItem(json: String): ProductItem {
        fun getStr(key: String): String {
            val k = "\"$key\""
            val start = json.indexOf(k)
            if (start < 0) return ""
            val colon = json.indexOf(":", start + k.length)
            val vStart = json.indexOf("\"", colon + 1)
            if (vStart < 0) {
                val end = json.indexOfAny(charArrayOf(',', '}'), colon + 1)
                return json.substring(colon + 1, end).trim()
            }
            val vEnd = json.indexOf("\"", vStart + 1)
            return json.substring(vStart + 1, vEnd)
        }
        fun getInt(key: String): Int {
            val k = "\"$key\""
            val start = json.indexOf(k)
            if (start < 0) return 0
            val colon = json.indexOf(":", start + k.length)
            val end = json.indexOfAny(charArrayOf(',', '}'), colon + 1)
            return json.substring(colon + 1, end).trim().toIntOrNull() ?: 0
        }
        fun getDouble(key: String): Double {
            val k = "\"$key\""
            val start = json.indexOf(k)
            if (start < 0) return 0.0
            val colon = json.indexOf(":", start + k.length)
            val end = json.indexOfAny(charArrayOf(',', '}'), colon + 1)
            return json.substring(colon + 1, end).trim().toDoubleOrNull() ?: 0.0
        }
        return ProductItem(
            id = getInt("id"),
            productId = getStr("barcode"),
            productName = getStr("name"),
            category = getStr("category"),
            stock = getInt("stock"),
            price = getDouble("price"),
            maxCapacity = getInt("max_capacity"),
            reorderLevel = getInt("reorder_level")
        )
    }

    private fun showQuantityDialog(product: ProductItem, action: String) {
        val actionLabel = if (action == "sell") "卖出" else "进货"
        val input = EditText(this).apply {
            hint = "请输入数量"
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
        }

        AlertDialog.Builder(this)
            .setTitle(product.productName + " -- " + actionLabel)
            .setMessage("库存: " + product.stock)
            .setView(input)
            .setPositiveButton("确认") { _, _ ->
                val qty = input.text.toString().toIntOrNull() ?: 1
                if (action == "restock") {
                    startRestockCountdown(product, qty)
                } else {
                    executeSellApi(product, qty)
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    // ========== Pending restock countdown logic ==========
    private var pendingRestock: PendingRestock? = null
    private var countdownTimer: CountDownTimer? = null
    private val RESTOCK_COUNTDOWN_SEC = 5

    private fun startRestockCountdown(product: ProductItem, qty: Int) {
        countdownTimer?.cancel()

        val pending = PendingRestock(
            barcode = product.productId,
            qty = qty,
            countdownSec = RESTOCK_COUNTDOWN_SEC,
            productName = product.productName
        )
        pendingRestock = pending
        productAdapter.setPendingRestock(pending)
        currentStatusTextView.text = "进货倒数: " + product.productName + " x" + qty + " (" + pending.countdownSec + "s)"

        countdownTimer = object : CountDownTimer((RESTOCK_COUNTDOWN_SEC * 1000).toLong(), 1000) {
            override fun onTick(millisUntilFinished: Long) {
                val sec = (millisUntilFinished / 1000).toInt() + 1
                pending.countdownSec = sec
                productAdapter.setPendingRestock(pending)
                runOnUiThread {
                    currentStatusTextView.text = "进货倒数: " + product.productName + " x" + qty + " (" + sec + "s)"
                }
            }

            override fun onFinish() {
                pendingRestock = null
                productAdapter.setPendingRestock(null)
                executeRestockApi(product, qty)
            }
        }.start()
    }

    private fun harvestRestock(product: ProductItem) {
        countdownTimer?.cancel()
        val pending = pendingRestock
        if (pending != null) {
            pendingRestock = null
            productAdapter.setPendingRestock(null)
            showToast("收获 " + product.productName + " x" + pending.qty)
            currentStatusTextView.text = "收获 " + product.productName + " x" + pending.qty
            executeRestockApi(product, pending.qty)
        }
    }

    private fun executeRestockApi(product: ProductItem, qty: Int) {
        thread {
            try {
                val body = "{\"barcode\":\"" + product.productId + "\",\"qty\":" + qty + "}"
                val result = httpPost("/restock", body)
                if (result == null) {
                    runOnUiThread { showToast("API request failed, check server") }
                    return@thread
                }

                runOnUiThread {
                    showToast("进货加库存 " + product.productName + " x" + qty)
                    currentStatusTextView.text = "进货加库存 " + product.productName + " x" + qty
                    alertList.add(0, AlertLog(
                        product.category,
                        "进货加库存 " + product.productName + " x" + qty,
                        SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
                    ))
                    adapter.notifyItemInserted(0)
                    showSystemNotification("进货加库存", product.productName + " x" + qty)
                }
                loadProducts()
            } catch (e: Exception) {
                runOnUiThread { showToast("Operation failed: " + e.message) }
            }
        }
    }

    private fun executeSellApi(product: ProductItem, qty: Int) {
        thread {
            try {
                val body = "{\"barcode\":\"" + product.productId + "\",\"qty\":" + qty + "}"
                val result = httpPost("/sell", body)
                if (result == null) {
                    runOnUiThread { showToast("API request failed, check server") }
                    return@thread
                }

                runOnUiThread {
                    showToast("卖出完成 " + product.productName + " x" + qty)
                    currentStatusTextView.text = "卖出完成 " + product.productName + " x" + qty
                    alertList.add(0, AlertLog(
                        product.category,
                        "卖出完成 " + product.productName + " x" + qty,
                        SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
                    ))
                    adapter.notifyItemInserted(0)
                    showSystemNotification("卖出完成", product.productName + " x" + qty)
                }
                loadProducts()
            } catch (e: Exception) {
                runOnUiThread { showToast("Operation failed: " + e.message) }
            }
        }
    }

    private fun startWebServer() {
        thread {
            try {
                server = embeddedServer(Netty, port = 8510, host = "0.0.0.0") {
                    install(ContentNegotiation) { gson() }
                    routing {
                        post("/notify") {
                            val body = call.receive<Map<String, String>>()
                            val items = body["message"] ?: "Unknown item"
                            val aisle = body["aisle"] ?: "Aisle 1"
                            val time = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())

                            runOnUiThread {
                                currentStatusTextView.text = "Low stock: " + aisle + "\n" + items
                                alertList.add(AlertLog(aisle, items, time))
                                adapter.notifyItemInserted(alertList.size - 1)
                                findViewById<RecyclerView>(R.id.recyclerView).smoothScrollToPosition(alertList.size - 1)
                                showSystemNotification("USI Restock Alert", items)
                            }
                            call.respond(mapOf("status" to "success"))
                        }
                    }
                }
                server?.start(wait = true)
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    // ========== Product List Adapter ==========
    inner class ProductAdapter(
        private val items: List<ProductItem>,
        private val onAction: (ProductItem, String) -> Unit
    ) : RecyclerView.Adapter<ProductAdapter.ViewHolder>() {

        private var currentPending: PendingRestock? = null
        private var harvestCallback: ((ProductItem) -> Unit)? = null

        fun setOnHarvestListener(cb: (ProductItem) -> Unit) {
            harvestCallback = cb
        }

        fun setPendingRestock(pending: PendingRestock?) {
            currentPending = pending
            notifyDataSetChanged()
        }

        inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            val nameText: TextView = view.findViewById(R.id.productName)
            val stockText: TextView = view.findViewById(R.id.productStock)
            val priceText: TextView = view.findViewById(R.id.productPrice)
            val sellBtn: Button = view.findViewById(R.id.sellBtn)
            val restockBtn: Button = view.findViewById(R.id.restockBtn)
            val countdownLayout: View = view.findViewById(R.id.countdownLayout)
            val countdownText: TextView = view.findViewById(R.id.countdownText)
            val harvestBtn: Button = view.findViewById(R.id.harvestBtn)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_product, parent, false)
            return ViewHolder(view)
        }

        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            val item = items[position]
            holder.nameText.text = item.productName
            holder.stockText.text = "Stock: " + item.stock
            holder.priceText.text = "$" + String.format("%.0f", item.price)
            holder.sellBtn.setOnClickListener { onAction(item, "sell") }
            holder.restockBtn.setOnClickListener { onAction(item, "restock") }

            val pending = currentPending
            if (pending != null && pending.barcode == item.productId) {
                holder.sellBtn.visibility = View.GONE
                holder.restockBtn.visibility = View.GONE
                holder.countdownLayout.visibility = View.VISIBLE
                holder.countdownText.text = "进货倒数: " + pending.qty + "个 (" + pending.countdownSec + "s)"
                holder.harvestBtn.setOnClickListener {
                    harvestCallback?.invoke(item)
                }
            } else {
                holder.sellBtn.visibility = View.VISIBLE
                holder.restockBtn.visibility = View.VISIBLE
                holder.countdownLayout.visibility = View.GONE
            }
        }

        override fun getItemCount() = items.size
    }

    class AlertAdapter(private val logs: List<AlertLog>) : RecyclerView.Adapter<AlertAdapter.ViewHolder>() {
        class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            val content: TextView = view.findViewById(android.R.id.text1)
        }
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context).inflate(android.R.layout.simple_list_item_1, parent, false)
            return ViewHolder(view)
        }
        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            val log = logs[position]
            holder.content.apply {
                textSize = 15f
                text = "[" + log.time + "] " + log.aisle + "\n" + log.items
                setPadding(15, 15, 15, 15)
                setBackgroundResource(android.R.drawable.editbox_dropdown_light_frame)
            }
        }
        override fun getItemCount() = logs.size
    }

    private fun showSystemNotification(title: String, message: String) {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title).setContentText(message)
            .setPriority(NotificationCompat.PRIORITY_HIGH).setAutoCancel(true)
        notificationManager.notify(System.currentTimeMillis().toInt(), builder.build())
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(CHANNEL_ID, "Restock Alert", NotificationManager.IMPORTANCE_HIGH)
            val notificationManager = getSystemService(NotificationManager::class.java)
            notificationManager?.createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        countdownTimer?.cancel()
        thread { server?.stop(500, 1000) }
    }
}
